#!/usr/bin/env python3
"""Source venues in south banlieue (94, 92 southern towns) via OSM Overpass + open data.

Outputs a JSONL file with venue observations that can be fed into the AI classify pipeline.
"""
from __future__ import annotations
import json, urllib.request, urllib.parse, time, re, sys
from pathlib import Path
from datetime import datetime

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# South banlieue communes we want to cover densely
SOUTH_COMMUNES = [
    # 94 - Val-de-Marne sud
    "Cachan", "Châtillon", "Montrouge", "Bagneux", "Arcueil", "Gentilly",
    "Villejuif", "Malakoff", "Vanves", "Clamart", "Fontenay-aux-Roses",
    "Le Kremlin-Bicêtre", "Ivry-sur-Seine", "Vitry-sur-Seine", "Choisy-le-Roi",
    "Thiais", "Orly", "Villeneuve-Saint-Georges", "Saint-Maur-des-Fossés",
    "Joinville-le-Pont", "Nogent-sur-Marne", "Bry-sur-Marne", "Champigny-sur-Marne",
    # 92 - Hauts-de-Seine sud
    "Antony", "Sceaux", "Châtenay-Malabry", "Puteaux", "Nanterre",
    "Issy-les-Moulineaux", "Meudon", "Boulogne-Billancourt",
]
IDF_SOUTH_BBOX = "48.7;2.1;48.95;2.55"  # lat_s, lon_w, lat_n, lon_e

def query_overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": "salles-idf-sig/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
            else:
                print(f"Overpass error after {attempt+1} attempts: {e}", file=sys.stderr)
                return {}

def overpass_query():
    """Query OSM for community centres, training rooms, yoga, dance, dojo in south IDF."""
    return f"""
[out:json][timeout:180];
(
  node["amenity"="community_centre"]({IDF_SOUTH_BBOX});
  way["amenity"="community_centre"]({IDF_SOUTH_BBOX});
  node["leisure"="training"]({IDF_SOUTH_BBOX});
  way["leisure"="training"]({IDF_SOUTH_BBOX});
  node["leisure"="dance"]({IDF_SOUTH_BBOX});
  way["leisure"="dance"]({IDF_SOUTH_BBOX});
  node["leisure"="sports_centre"]({IDF_SOUTH_BBOX});
  way["leisure"="sports_centre"]({IDF_SOUTH_BBOX});
  node["amenity"=".events_venue"]({IDF_SOUTH_BBOX});
  way["amenity"="events_venue"]({IDF_SOUTH_BBOX});
  node["building"="yes"]["name"~"salle|mairie|espace|centre|dojo|studio",i]({IDF_SOUTH_BBOX});
  way["building"="yes"]["name"~"salle|mairie|espace|centre|dojo|studio",i]({IDF_SOUTH_BBOX});
  nwr["office"~"association|ngo"]({IDF_SOUTH_BBOX});
);
out center;
"""

def extract_venues(data: dict) -> list[dict]:
    venues = []
    elements = data.get("elements", [])
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            continue
        # Filter out large venues, bars, restaurants unless they look like rentable rooms
        amenity = tags.get("amenity", "")
        leisure = tags.get("leisure", "")
        building = tags.get("building", "")
        if amenity in ("bar", "restaurant", "cafe", "fast_food", "pub", "nightclub", "cinema", "theatre"):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat", "")
        lon = el.get("lon") or el.get("center", {}).get("lon", "")
        if not lat or not lon:
            continue
        city = tags.get("addr:city", "") or tags.get("address:city", "")
        postcode = tags.get("addr:postcode", "")
        street = tags.get("addr:street", "")
        addr = f"{street}, {postcode} {city}".strip(", ").strip() if street or city else ""
        website = tags.get("website") or tags.get("contact:website", "")
        phone = tags.get("phone") or tags.get("contact:phone", "")
        capacity = tags.get("capacity", "")
        venue_type = amenity or leisure or building or "venue"
        venues.append({
            "source": "osm_overpass",
            "source_id": f"osm_{el.get('type','n')}_{el.get('id','')}",
            "name": name,
            "city": city,
            "department": postcode[:2] if postcode and postcode[:2] in {"75","77","78","91","92","93","94","95"} else "",
            "address": addr,
            "postal_code": postcode,
            "lat": str(lat),
            "lon": str(lon),
            "website": website,
            "phone": phone,
            "capacity": capacity,
            "category": venue_type,
            "osm_type": el.get("type",""),
            "osm_id": el.get("id",""),
            "tags_dump": {k:v for k,v in tags.items() if k.startswith(("name","amen","leis","addr","capa","webs","phon","contact","build","offic","room","sport","yoga","dance","dojo","hall"))},
        })
    return venues

def main():
    outdir = Path("data/discovery_runs/south_banlieue_osm")
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / f"osm_south_banlieue_{datetime.now().strftime('%Y%m%d')}.json"
    
    print(f"Querying Overpass for south IDF venues...")
    data = query_overpass(overpass_query())
    
    if not data or "elements" not in data:
        print(f"Overpass query failed or returned no data", file=sys.stderr)
        sys.exit(1)
    
    venues = extract_venues(data)
    print(f"Found {len(venues)} candidate venues from {len(data.get('elements',[]))} OSM elements")
    
    # Filter to south communes more precisely
    south_set = {c.lower().replace("-", " ").replace("î", "i").replace("â", "a").replace("é", "e").replace("è", "e") 
                 for c in SOUTH_COMMUNES}
    filtered = []
    for v in venues:
        city_l = v["city"].lower().replace("-", " ").replace("î", "i").replace("â", "a").replace("é", "e").replace("è", "e")
        dept = v["department"]
        # Department 94 or 92, or city matches
        if dept in ("94", "92") or city_l in south_set or not v["city"]:
            filtered.append(v)
    
    print(f"Filtered to {len(filtered)} venues in south banlieue (94, 92 southern)")
    
    outfile.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written to {outfile}")
    
    # Summary
    by_dept = {}
    for v in filtered:
        d = v["department"] or "?"
        by_dept[d] = by_dept.get(d, 0) + 1
    print(f"By department: {by_dept}")
    
    return filtered

if __name__ == "__main__":
    main()
