#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from common import ROOT, read_records, write_csv, norm_text, now_iso
from normalize_candidate import normalize_records
from match_existing import match_candidate


def demo_records():
    return [
      {'name':'Studio Danse République','city':'Paris','address':'10 rue fictive, Paris','website':'https://studio-danse-demo.example/location','source_url':'https://studio-danse-demo.example/location','source_type':'studio_website','source_confidence':'high','description':'Location studio danse avec parquet, miroirs, salle vide pour atelier mouvement et cercle. Musique autorisée.','contact':'contact@studio.example','price_text':'35€/h','capacity_text':'18 personnes'},
      {'name':'Dojo Associatif Montreuil','city':'Montreuil','address':'5 avenue exemple, Montreuil','source_url':'https://dojo-demo.example','source_type':'studio_website','source_confidence':'high','description':'Dojo avec tatami, pratique corporelle, location ponctuelle possible, assurance requise.','contact':'','price_text':'à confirmer','capacity_text':'20 personnes'},
      {'name':'Cowork Premium Opéra','city':'Paris','address':'1 place exemple, Paris','source_url':'https://cowork-premium.example','source_type':'aggregator','source_confidence':'medium','description':'Salle de réunion corporate avec tables fixes, écran, séminaire premium.','contact':'sales@example.com','price_text':'250€/demi-journée','capacity_text':'12 places assises'}]


def load_existing_venues(path: Path):
    if not path.exists():
        return []
    data=json.loads(path.read_text(encoding='utf-8'))
    venues=[]
    for f in data.get('features',[]):
        p=f.get('properties') or {}
        coords=(f.get('geometry') or {}).get('coordinates') or []
        venues.append({
            'venue_id': p.get('id') or p.get('venue_id') or p.get('name'),
            'name': p.get('name') or p.get('canonical_name') or '',
            'canonical_name': p.get('name') or p.get('canonical_name') or '',
            'city': p.get('city') or '',
            'department': p.get('department') or '',
            'address': p.get('address') or '',
            'canonical_website': p.get('website') or p.get('canonical_website') or '',
            'lat': coords[1] if len(coords)>=2 else p.get('lat'),
            'lon': coords[0] if len(coords)>=2 else p.get('lon'),
        })
    return venues


def dedupe_candidates(candidates):
    kept=[]; seen={}; duplicates=[]
    for c in candidates:
        key=c.get('dedupe_key') or '|'.join([norm_text(c.get('name')), norm_text(c.get('city')), norm_text(c.get('address'))])
        if key in seen:
            c['candidate_status']='duplicate_suspect'
            c['duplicate_of']=seen[key]
            duplicates.append(c)
            continue
        seen[key]=c['candidate_id']
        kept.append(c)
    return kept, duplicates


def apply_existing_matches(candidates, existing):
    matched=[]
    for c in candidates:
        matches=match_candidate(c, existing) if existing else []
        if matches:
            c['candidate_status']='duplicate_suspect'
            c['duplicate_of']=matches[0]['venue_id']
            c['match_score']=matches[0]['score']
            c['match_reasons']='|'.join(matches[0]['reasons'])
            c['matches_json']=json.dumps(matches, ensure_ascii=False)
            matched.append(c)
        else:
            c.setdefault('candidate_status','new')
            c.setdefault('duplicate_of','')
            c.setdefault('match_score','')
            c.setdefault('match_reasons','')
            c.setdefault('matches_json','[]')
    return matched


def to_geojson(candidates):
    feats=[]
    for c in candidates:
        try:
            lon=float(c.get('lon')) if c.get('lon') not in (None,'') else None
            lat=float(c.get('lat')) if c.get('lat') not in (None,'') else None
        except Exception:
            lon=lat=None
        geom={'type':'Point','coordinates':[lon,lat]} if lon is not None and lat is not None else None
        feats.append({'type':'Feature','geometry':geom,'properties':c})
    return {'type':'FeatureCollection','features':feats, 'metadata': {'generated_at': now_iso(), 'note': 'geometry is null when address has not been geocoded yet'}}


def write_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('input', nargs='?', help='CSV/JSON source records or candidate-like records')
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--existing', default=str(ROOT/'public/salles_all_idf.geojson'))
    ap.add_argument('--date', default=now_iso()[:10].replace('-',''))
    args=ap.parse_args()

    records=demo_records() if args.demo or not args.input else read_records(args.input)
    candidates=normalize_records(records)
    deduped, intra_duplicates=dedupe_candidates(candidates)
    existing=load_existing_venues(Path(args.existing))
    existing_matches=apply_existing_matches(deduped, existing)

    cand_json=ROOT/f'data/candidates/candidates_{args.date}.json'
    cand_csv=ROOT/f'data/candidates/candidates_{args.date}.csv'
    queue_csv=ROOT/'data/import_queue/import_queue.csv'
    queue_geo=ROOT/'public/import_queue.geojson'
    duplicates_json=ROOT/f'data/import_queue/duplicates_{args.date}.json'
    report_path=ROOT/f'data/import_queue/report_{args.date}.json'

    # Import queue contains candidates not already matched to existing and not intra-duplicates.
    queue=[c for c in deduped if c.get('candidate_status')!='duplicate_suspect']

    fields=sorted({k for r in deduped+queue for k in r})
    write_json(cand_json, deduped)
    write_csv(cand_csv, deduped, fields)
    write_csv(queue_csv, queue, fields)
    write_json(queue_geo, to_geojson(queue))
    write_json(duplicates_json, {'intra_duplicates': intra_duplicates, 'existing_matches': existing_matches})

    mapped_queue = [c for c in queue if c.get('lat') not in (None, '') and c.get('lon') not in (None, '')]
    report={
      'generated_at': now_iso(),
      'input_records': len(records),
      'normalized_candidates': len(candidates),
      'deduped_candidates': len(deduped),
      'intra_duplicates': len(intra_duplicates),
      'existing_matches': len(existing_matches),
      'import_queue': len(queue),
      'mapped_import_queue': len(mapped_queue),
      'unmapped_import_queue': len(queue) - len(mapped_queue),
      'by_department_mapped': dict(sorted(Counter(c.get('department') or '?' for c in mapped_queue).items())),
      'by_city_mapped_top20': dict(Counter(c.get('city') or '?' for c in mapped_queue).most_common(20)),
      'aggregator_items': sum(1 for c in queue if str(c.get('is_aggregator') or '').lower() == 'yes'),
      'scraped_items': sum(1 for c in queue if c.get('formal_extraction_status') == 'scraped'),
      'scrape_failed_items': sum(1 for c in queue if 'failed' in str(c.get('formal_extraction_status') or '')),
      'formal_complete_items': sum(1 for c in queue if str(c.get('formal_completeness_score') or '') == '4'),
      'missing_formal_fields_distribution': dict(Counter(c.get('missing_formal_fields') or 'none' for c in queue).most_common(20)),
      'high_fit_80_plus': sum(1 for c in queue if int(float(c.get('fit_beyond_score') or 0)) >= 80),
      'medium_fit_60_plus': sum(1 for c in queue if int(float(c.get('fit_beyond_score') or 0)) >= 60),
      'with_contact': sum(1 for c in queue if c.get('contact')),
      'with_price': sum(1 for c in queue if c.get('price_text')),
      'with_capacity': sum(1 for c in queue if c.get('capacity_text') or c.get('capacity_max')),
      'outputs': {
        'candidates_json': str(cand_json),
        'candidates_csv': str(cand_csv),
        'import_queue_csv': str(queue_csv),
        'import_queue_geojson': str(queue_geo),
        'duplicates_json': str(duplicates_json),
      }
    }
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
