#!/usr/bin/env python3
from common import write_csv, read_records, ROOT
from normalize_candidate import normalize_records
import argparse, json

def demo_records():
    return [
      {'name':'Studio Danse République','city':'Paris','address':'10 rue fictive, Paris','website':'https://studio-danse-demo.example/location','source_url':'https://studio-danse-demo.example/location','source_type':'studio_website','source_confidence':'high','description':'Location studio danse avec parquet, miroirs, salle vide pour atelier mouvement et cercle. Musique autorisée.','contact':'contact@studio.example','price_text':'35€/h','capacity_text':'18 personnes'},
      {'name':'Dojo Associatif Montreuil','city':'Montreuil','address':'5 avenue exemple, Montreuil','source_url':'https://dojo-demo.example','source_type':'studio_website','source_confidence':'high','description':'Dojo avec tatami, pratique corporelle, location ponctuelle possible, assurance requise.','contact':'','price_text':'à confirmer','capacity_text':'20 personnes'},
      {'name':'Cowork Premium Opéra','city':'Paris','address':'1 place exemple, Paris','source_url':'https://cowork-premium.example','source_type':'aggregator','source_confidence':'medium','description':'Salle de réunion corporate avec tables fixes, écran, séminaire premium.','contact':'sales@example.com','price_text':'250€/demi-journée','capacity_text':'12 places assises'}]

def to_geojson(candidates):
    feats=[]
    for c in candidates:
        try: lon=float(c.get('lon') or 0); lat=float(c.get('lat') or 0)
        except Exception: lon=lat=0
        feats.append({'type':'Feature','geometry':{'type':'Point','coordinates':[lon,lat]},'properties':c})
    return {'type':'FeatureCollection','features':feats}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('input', nargs='?'); ap.add_argument('--demo', action='store_true'); args=ap.parse_args()
    records=demo_records() if args.demo or not args.input else read_records(args.input)
    candidates=normalize_records(records)
    out_csv=ROOT/'data/import_queue/import_queue.csv'; out_geo=ROOT/'public/import_queue.geojson'
    write_csv(out_csv, candidates)
    out_geo.parent.mkdir(parents=True, exist_ok=True); out_geo.write_text(json.dumps(to_geojson(candidates),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'wrote {len(candidates)} candidates to {out_csv} and {out_geo}')
if __name__=='__main__': main()
