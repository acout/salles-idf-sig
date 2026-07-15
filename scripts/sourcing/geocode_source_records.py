#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import now_iso

for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
    os.environ.pop(_k, None)

IDF_BBOX = (48.1, 49.1, 1.4, 3.6)  # minLat, maxLat, minLon, maxLon


def inside_idf(lat: float, lon: float) -> bool:
    min_lat, max_lat, min_lon, max_lon = IDF_BBOX
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def geocode_one(record: dict) -> dict:
    rec = dict(record)
    if rec.get('lat') not in (None, '') and rec.get('lon') not in (None, ''):
        rec.setdefault('geocode_status', 'already_had_coordinates')
        return rec
    address = str(rec.get('address') or '').strip()
    city = str(rec.get('city') or '').strip()
    if not address:
        rec['geocode_status'] = 'missing_address'
        return rec
    q = f'{address}, {city}' if city and city.lower() not in address.lower() else address
    url = 'https://api-adresse.data.gouv.fr/search/?' + urllib.parse.urlencode({'q': q, 'limit': 1})
    req = urllib.request.Request(url, headers={'User-Agent': 'Hermes salles-idf-sig formal-geocoder/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
    except Exception as e:
        rec['geocode_status'] = f'fetch_failed:{type(e).__name__}'
        return rec
    feats = data.get('features') or []
    if not feats:
        rec['geocode_status'] = 'not_found'
        return rec
    f = feats[0]
    lon, lat = f.get('geometry', {}).get('coordinates', [None, None])
    props = f.get('properties', {})
    if lat is None or lon is None:
        rec['geocode_status'] = 'invalid_response'
        return rec
    lat = float(lat); lon = float(lon)
    score = props.get('score')
    if not inside_idf(lat, lon):
        rec['geocode_status'] = 'outside_idf'
        rec['geocode_candidate_label'] = props.get('label', '')
        rec['geocode_candidate_score'] = score
        return rec
    if score is not None and float(score) < 0.35:
        rec['geocode_status'] = 'low_score'
        rec['geocode_candidate_label'] = props.get('label', '')
        rec['geocode_candidate_score'] = score
        return rec
    rec['lat'] = lat
    rec['lon'] = lon
    rec['geocode_score'] = score
    rec['geocode_label'] = props.get('label', '')
    rec['geocode_status'] = 'geocoded_ban'
    return rec


def main():
    ap = argparse.ArgumentParser(description='Geocode source records with address but no coordinates using BAN API.')
    ap.add_argument('input')
    ap.add_argument('--output', required=True)
    ap.add_argument('--report', default='')
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()
    records = json.loads(Path(args.input).read_text(encoding='utf-8'))
    started = time.time()
    out = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for rec in pool.map(geocode_one, records):
            out.append(rec)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    statuses = {}
    for r in out:
        s = r.get('geocode_status', 'unknown')
        statuses[s] = statuses.get(s, 0) + 1
    report = {
        'generated_at': now_iso(),
        'input_records': len(records),
        'output_records': len(out),
        'with_coordinates': sum(1 for r in out if r.get('lat') not in (None, '') and r.get('lon') not in (None, '')),
        'statuses': statuses,
        'duration_seconds': round(time.time() - started, 1),
        'output': str(output),
    }
    report_path = Path(args.report) if args.report else output.with_suffix('.report.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
