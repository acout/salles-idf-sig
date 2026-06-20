#!/usr/bin/env python3
from common import read_records, now_iso, norm_text
from stable_id import source_record_id, candidate_id, dedupe_key
from score_beyond import score_candidate
import argparse, json, re

def guess_tags(text):
    t=norm_text(text); acts=[]; spaces=[]; cons=[]; cat=''
    pairs=[('danse','dance','studio_danse'),('yoga','yoga','studio_yoga'),('dojo','dojo','dojo'),('theatre','theatre','salle_theatre'),('répétition','theatre','salle_theatre'),('repetition','theatre','salle_theatre'),('meditation','meditation','centre_bien_etre'),('bien etre','bodywork','centre_bien_etre'),('mjc','group_interaction','mjc'),('maison associations','circle','maison_associations'),('cowork','', 'coworking')]
    for kw,tag,c in pairs:
        if norm_text(kw) in t:
            if tag: acts.append(tag)
            cat=cat or c
    for kw,tag in [('salle vide','empty_room'),('open floor','open_floor'),('parquet','wood_floor'),('tatami','tatami'),('miroir','mirrors'),('modulable','modular')]:
        if norm_text(kw) in t: spaces.append(tag)
    for kw,tag in [('bruit interdit','no_noise'),('musique interdite','no_music'),('tables fixes','tables_fixed'),('premium','premium_price')]:
        if norm_text(kw) in t: cons.append(tag)
    return sorted(set(acts)), sorted(set(spaces)), sorted(set(cons)), cat or 'needs_classification'
def normalize_record(r):
    name=r.get('name') or r.get('raw_name') or r.get('Nom') or r.get('title') or ''
    city=r.get('city') or r.get('raw_city') or r.get('Ville') or ''
    address=r.get('address') or r.get('raw_address') or r.get('Adresse') or ''
    source_url=r.get('source_url') or r.get('url') or r.get('website') or ''
    description=' '.join(str(r.get(k,'')) for k in ('description','raw_description','evidence_text','category_guess','name','raw_name'))
    acts,spaces,cons,cat=guess_tags(description+' '+name)
    sid=r.get('source_record_id') or source_record_id(source_url,name,address)
    c={
      'candidate_id': candidate_id(name,city,address,source_url), 'source_record_id': sid, 'name': name, 'normalized_name': norm_text(name), 'address': address, 'city': city,
      'department': r.get('department') or r.get('Département') or '', 'lat': r.get('lat') or None, 'lon': r.get('lon') or None,
      'website': r.get('website') or source_url, 'contact': r.get('contact') or r.get('raw_contact') or '', 'capacity_text': r.get('capacity_text') or r.get('raw_capacity') or '',
      'price_text': r.get('price_text') or r.get('raw_price') or '', 'description': description.strip(), 'activity_tags': acts, 'space_tags': spaces, 'constraints_tags': cons,
      'category': r.get('category') or r.get('category_guess') or cat, 'source_url': source_url, 'source_type': r.get('source_type') or 'manual', 'source_confidence': r.get('source_confidence') or 'unknown',
      'evidence_text': r.get('evidence_text') or description[:500], 'dedupe_key': dedupe_key(name,city,address,source_url), 'candidate_status': 'new', 'last_seen_at': now_iso()[:10]
    }
    # Formal enrichment / aggregator metadata is additive and non-destructive.
    for key in (
        'is_aggregator', 'aggregator_domain', 'aggregator_child_links_count', 'parent_aggregator_url', 'parent_aggregator_name',
        'formal_scrape_checked_at', 'formal_scrape_http_status', 'formal_scrape_content_type', 'formal_extraction_status',
        'formal_address_source', 'geocode_status', 'geocode_candidate_label', 'geocode_candidate_score',
        'formal_page_title', 'formal_evidence_text', 'formal_contact_source', 'formal_price_source', 'formal_capacity_source',
        'missing_formal_fields', 'email_questions', 'formal_completeness_score', 'target_run'
    ):
        if r.get(key) not in (None, ''):
            c[key] = r.get(key)
    c.update(score_candidate(c)); return c
def normalize_records(records): return [normalize_record(r) for r in records if (r.get('name') or r.get('raw_name') or r.get('Nom') or r.get('title'))]
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('input'); ap.add_argument('--json', action='store_true'); a=ap.parse_args()
    out=normalize_records(read_records(a.input)); print(json.dumps(out,ensure_ascii=False,indent=2) if a.json else '\n'.join(json.dumps(x,ensure_ascii=False) for x in out))
