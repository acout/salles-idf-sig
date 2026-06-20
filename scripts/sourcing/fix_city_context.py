#!/usr/bin/env python3
"""Fix missing city/department in import_queue features by propagating from parent entity context."""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

KNOWN_CITIES = {
    'fontenay-aux-roses': ('Fontenay-aux-Roses', '92'),
    'chevilly-larue': ('Chevilly-Larue', '94'),
    'cachan': ('Cachan', '94'),
    'chatillon': ('Châtillon', '92'),
    'châtillon': ('Châtillon', '92'),
    'vanves': ('Vanves', '92'),
    'meudon': ('Meudon', '92'),
    'fresnes': ('Fresnes', '94'),
    'orly': ('Orly', '94'),
    'charenton-le-pont': ('Charenton-le-Pont', '94'),
    'bougival': ('Bougival', '78'),
    'le plessis-robinson': ('Le Plessis-Robinson', '92'),
    'chatenay-malabry': ('Châtenay-Malabry', '92'),
    'châtenay-malabry': ('Châtenay-Malabry', '92'),
    "l'haÿ-les-roses": ("L'Haÿ-les-Roses", '94'),
    "lhay-les-roses": ("L'Haÿ-les-Roses", '94'),
    'paris': ('Paris', '75'),
    'clamart': ('Clamart', '92'),
    'malakoff': ('Malakoff', '92'),
    'montrouge': ('Montrouge', '92'),
    'bagneux': ('Bagneux', '92'),
    'arcueil': ('Arcueil', '94'),
    'gentilly': ('Gentilly', '94'),
    'villejuif': ('Villejuif', '94'),
    'sceaux': ('Sceaux', '92'),
    'kremlin-bicêtre': ('Le Kremlin-Bicêtre', '94'),
    'kremlin bicetre': ('Le Kremlin-Bicêtre', '94'),
    'ivry-sur-seine': ('Ivry-sur-Seine', '94'),
    'vitry-sur-seine': ('Vitry-sur-Seine', '94'),
    'choisy-le-roi': ('Choisy-le-Roi', '94'),
    'antony': ('Antony', '92'),
    'bourg-la-reine': ('Bourg-la-Reine', '92'),
    'issy-les-moulineaux': ('Issy-les-Moulineaux', '92'),
    'boulogne-billancourt': ('Boulogne-Billancourt', '92'),
    'rungis': ('Rungis', '94'),
    'joinville-le-pont': ('Joinville-le-Pont', '94'),
    'nogent-sur-marne': ('Nogent-sur-Marne', '94'),
    'vincennes': ('Vincennes', '94'),
    'saint-mandé': ('Saint-Mandé', '94'),
    'saint-mandé': ('Saint-Mandé', '94'),
}

def norm(s):
    return s.lower().replace('-', ' ').replace('â', 'a').replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('î', 'i').replace('ô', 'o').replace('ù', 'u').replace('ç', 'c').replace("'", ' ')

def find_city(text):
    t = norm(text)
    for key, (city, dept) in KNOWN_CITIES.items():
        if key in t:
            return city, dept
    return '', ''

# Load import queue
iq_path = ROOT / 'public' / 'import_queue.geojson'
q = json.loads(iq_path.read_text(encoding='utf-8'))

fixed = 0
for f in q['features']:
    p = f['properties']
    if p.get('city') and p['city'] not in ('', '?'):
        continue
    
    # Try name, address, evidence_text, source_url
    candidates = [p.get('name', ''), p.get('address', ''), p.get('evidence_text', ''),
                  p.get('source_url', ''), p.get('website', '')]
    for text in candidates:
        if not text:
            continue
        city, dept = find_city(text)
        if city:
            p['city'] = city
            if not p.get('department') and dept:
                p['department'] = dept
            fixed += 1
            break

iq_path.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"Fixed {fixed} features with city/dept from text context")

# Rebuild address for features that now have city
for f in q['features']:
    p = f['properties']
    city = p.get('city', '')
    dept = p.get('department', '')
    addr = p.get('address', '')
    if city and city not in addr:
        if addr and addr != city:
            p['address'] = f"{addr}, {city}"
        else:
            p['address'] = city

iq_path.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding='utf-8')

# Count south
south_count = 0
south_cities = set()
for f in q['features']:
    c = norm(f['properties'].get('city', ''))
    for key in KNOWN_CITIES:
        if key in c:
            south_count += 1
            south_cities.add(f['properties'].get('city', ''))
            break

print(f"Banlieue sud: {south_count} salles")
print(f"Villes: {sorted(south_cities)}")