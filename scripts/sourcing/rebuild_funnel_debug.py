#!/usr/bin/env python3
"""Rebuild feature-level L4 import items in funnel_debug from import_queue."""
import json
from pathlib import Path
from collections import Counter

fd_path = Path('public/funnel_debug.json')
iq_path = Path('public/import_queue.geojson')

fd = json.loads(fd_path.read_text(encoding='utf-8'))
iq = json.loads(iq_path.read_text(encoding='utf-8'))

kept = [i for i in fd.get('items', []) if i.get('stage') != 'L4_import_queue']

features = []
for idx, f in enumerate(iq.get('features', [])):
    p = f.get('properties', {})
    coords = f.get('geometry', {}).get('coordinates') or [0, 0]
    has_coords = coords != [0, 0]
    missing = p.get('missing_formal_fields') or ''
    reason = 'Importé dans la carte/liste comme candidat final.'
    if not has_coords:
        reason += ' Pas encore de coordonnées fiables : visible en liste/Vérif Import, pas sur la carte.'
    if missing:
        reason += f' Infos à compléter: {missing}.'
    features.append({
        'venue_entity_id': p.get('candidate_id') or f'import_feature_{idx}',
        'feature_id': p.get('candidate_id') or f'import_feature_{idx}',
        'name': p.get('name') or 'Sans nom',
        'city': p.get('city') or '',
        'department': p.get('department') or '',
        'address': p.get('address') or '',
        'stage': 'L4_import_queue',
        'stop_reason': reason,
        'page_type': p.get('page_type') or p.get('ai_source_kind') or 'import_queue',
        'source_reliability': p.get('source_reliability') or '',
        'geo_status': p.get('geo_status') or ('geocoded' if has_coords else 'missing_coords'),
        'rental_possible': p.get('rental_possible_status') or '',
        'source_url': p.get('source_url') or p.get('website') or p.get('specific_rental_page_url') or '',
        'has_ai_retry_result': bool(p.get('ai_source_record_id') or p.get('ai_source_file')),
        'ai_source_file': p.get('ai_source_file') or '',
        'ai_source_kind': p.get('ai_source_kind') or '',
        'is_import_feature': True,
        'has_coords': has_coords,
        'contact': p.get('contact') or '',
        'price_text': p.get('price_text') or '',
        'capacity_text': p.get('capacity_text') or '',
        'capacity_max_detected': p.get('capacity_max_detected') or 0,
    })

fd['items'] = kept + features
fd['stage_counts'] = dict(Counter(i.get('stage', '') for i in fd['items']))
fd['import_feature_count'] = len(features)
fd_path.write_text(json.dumps(fd, ensure_ascii=False, indent=2), encoding='utf-8')

# Stats
has_cap = sum(1 for f in iq['features'] if f['properties'].get('capacity_text'))
has_price = sum(1 for f in iq['features'] if f['properties'].get('price_text'))
has_contact = sum(1 for f in iq['features'] if f['properties'].get('contact'))
has_addr = sum(1 for f in iq['features'] if f['properties'].get('address'))
print(f'L4={fd["stage_counts"]["L4_import_queue"]} cap={has_cap} price={has_price} contact={has_contact} addr={has_addr}')

# Show DOJO
for f in iq['features']:
    p = f['properties']
    if 'DOJO 5' in p.get('name', ''):
        print(f"  {p['name']}: cap={p.get('capacity_text','')[:60]}, max={p.get('capacity_max_detected')}, price={p.get('price_text','')[:60]}")