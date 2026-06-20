#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from common import ROOT, now_iso


def run(cmd: list[str]) -> None:
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def build_email_questions_csv(date: str) -> None:
    data = json.loads((ROOT / 'public/import_queue.geojson').read_text(encoding='utf-8'))
    rows = []
    for feature in data.get('features', []):
        p = feature.get('properties') or {}
        needs_email = (p.get('missing_formal_fields') or '').strip() or p.get('rental_possible_status') in ('unclear', 'unlikely')
        if not needs_email:
            continue
        rows.append({
            'name': p.get('name', ''), 'city': p.get('city', ''), 'department': p.get('department', ''),
            'is_aggregator': p.get('is_aggregator', ''), 'aggregator_domain': p.get('aggregator_domain', ''),
            'rental_possible_status': p.get('rental_possible_status', ''),
            'rental_possible_confidence': p.get('rental_possible_confidence', ''),
            'rental_positive_signals': p.get('rental_positive_signals', ''),
            'rental_negative_signals': p.get('rental_negative_signals', ''),
            'missing_formal_fields': p.get('missing_formal_fields', ''),
            'email_questions': p.get('email_questions', ''),
            'contact': p.get('contact', ''), 'price_text': p.get('price_text', ''),
            'capacity_text': p.get('capacity_text', ''), 'address': p.get('address', ''),
            'source_url': p.get('source_url', ''), 'formal_extraction_status': p.get('formal_extraction_status', ''),
            'formal_scrape_http_status': p.get('formal_scrape_http_status', ''),
        })
    out = ROOT / f'data/import_queue/email_questions_{date}.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ['name']
    with out.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    summary = {
        'generated_at': now_iso(),
        'rows_needing_email_or_rental_check': len(rows),
        'rental_unclear_or_unlikely': sum(1 for r in rows if r.get('rental_possible_status') in ('unclear', 'unlikely')),
        'output': str(out),
    }
    (ROOT / f'data/import_queue/email_questions_{date}.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description='Re-executable Beyond sourcing import pipeline: merge -> formal scrape -> geocode -> rental qualification -> queue -> email questions.')
    ap.add_argument('source_records', nargs='+', help='Source record JSON arrays to merge')
    ap.add_argument('--date', required=True, help='Run id/date, e.g. 20260620_rental')
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--skip-scrape', action='store_true', help='Use an already enriched input as the merge output; useful for debugging only')
    args = ap.parse_args()

    date = args.date
    combined = ROOT / f'data/source_records/combined_beyond_idf_{date}.json'
    enriched = ROOT / f'data/source_records/formal_enriched_beyond_idf_{date}.json'
    enriched_geo = ROOT / f'data/source_records/formal_enriched_geocoded_beyond_idf_{date}.json'
    rental = ROOT / f'data/source_records/rental_qualified_beyond_idf_{date}.json'

    run([sys.executable, 'scripts/sourcing/merge_source_records.py', *args.source_records,
         '--output', str(combined), '--summary-output', str(combined.with_suffix('.summary.json'))])

    if not args.skip_scrape:
        run([sys.executable, 'scripts/sourcing/enrich_formal_fields.py', str(combined),
             '--output', str(enriched), '--report', str(enriched.with_suffix('.report.json')), '--workers', str(args.workers)])
        # Check every final item after aggregator expansion, but do not expand recursively forever.
        checked = ROOT / f'data/source_records/formal_enriched_checked_all_beyond_idf_{date}.json'
        run([sys.executable, 'scripts/sourcing/enrich_formal_fields.py', str(enriched),
             '--output', str(checked), '--report', str(checked.with_suffix('.report.json')), '--workers', str(args.workers), '--no-expand-aggregators'])
    else:
        checked = combined

    run([sys.executable, 'scripts/sourcing/geocode_source_records.py', str(checked),
         '--output', str(enriched_geo), '--report', str(enriched_geo.with_suffix('.report.json')), '--workers', '8'])
    run([sys.executable, 'scripts/sourcing/qualify_rental_possibility.py', str(enriched_geo),
         '--output', str(rental), '--report', str(rental.with_suffix('.report.json'))])
    run([sys.executable, 'scripts/sourcing/build_import_queue.py', str(rental), '--date', date])
    build_email_questions_csv(date)


if __name__ == '__main__':
    main()
