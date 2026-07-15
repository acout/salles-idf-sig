#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from common import ROOT, now_iso


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def stable_key(record: dict) -> tuple[str, str, str, str]:
    return (
        str(record.get('source_url') or record.get('url') or record.get('website') or '').strip().lower(),
        str(record.get('name') or record.get('title') or record.get('raw_name') or '').strip().lower(),
        str(record.get('city') or record.get('raw_city') or '').strip().lower(),
        str(record.get('address') or record.get('raw_address') or '').strip().lower(),
    )


def main():
    ap = argparse.ArgumentParser(description='Merge multiple source_record JSON arrays without deleting previous sourcing waves.')
    ap.add_argument('inputs', nargs='+', help='Source record JSON files to merge')
    ap.add_argument('--output', default=str(ROOT / 'data/source_records/combined_beyond_idf.json'))
    ap.add_argument('--summary-output', default='')
    args = ap.parse_args()

    merged = []
    seen = set()
    duplicates = []
    per_file = {}

    for raw in args.inputs:
        path = Path(raw)
        records = load_json(path)
        per_file[str(path)] = len(records)
        for record in records:
            key = stable_key(record)
            if key in seen:
                duplicates.append(record)
                continue
            seen.add(key)
            merged.append(record)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')

    summary = {
        'generated_at': now_iso(),
        'inputs': per_file,
        'merged_records': len(merged),
        'source_level_duplicates_removed': len(duplicates),
        'geocoded_records': sum(1 for r in merged if r.get('lat') not in (None, '') and r.get('lon') not in (None, '')),
        'target_runs': sorted({r.get('target_run') for r in merged if r.get('target_run')}),
        'output': str(out),
    }
    summary_path = Path(args.summary_output) if args.summary_output else out.with_suffix('.summary.json')
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
