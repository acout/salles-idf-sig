#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import ROOT, blank, now_iso, read_records, short_hash, stable_id

SCHEMA_VERSION = '2026-06-20.v1'
TEXT_LIMIT = 12000


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def safe_domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(str(url or '')).netloc.replace('www.', '').lower()
    except Exception:
        return ''


def normalize_url(url: str) -> str:
    return str(url or '').split('#')[0].rstrip('/')


def as_str(v: Any) -> str:
    if v is None:
        return ''
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def first_nonblank(*vals: Any) -> str:
    for v in vals:
        s = as_str(v).strip()
        if not blank(s):
            return s
    return ''


def guess_provider(record: dict, default: str) -> str:
    return first_nonblank(record.get('provider'), record.get('source_provider'), record.get('source_engine'), record.get('api_provider'), default) or 'legacy_source_records'


def raw_rank(record: dict) -> Any:
    if not blank(record.get('provider_rank')):
        return record.get('provider_rank')
    raw = record.get('raw_json') or record.get('raw') or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if isinstance(raw, dict):
        return raw.get('position') or raw.get('rank') or raw.get('index') or ''
    return ''


def write_content(run_dir: Path, obs_id: str, text: str) -> tuple[str, str, str]:
    text = (text or '').strip()
    if not text:
        return '', '', ''
    sha = sha256_text(text)
    rel = Path('content_cache') / f'{obs_id}_{sha[:12]}.txt'
    out = run_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text[:TEXT_LIMIT], encoding='utf-8')
    return str(rel), sha, f'content_{sha[:12]}'


def write_raw_payload(run_dir: Path, obs_id: str, record: dict) -> tuple[str, str]:
    raw = json.dumps(record, ensure_ascii=False, indent=2)
    sha = sha256_text(raw)
    rel = Path('provider_raw') / f'{obs_id}_{sha[:12]}.json'
    out = run_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(raw, encoding='utf-8')
    return str(rel), sha


def observation_from_record(record: dict, run_id: str, run_dir: Path, source_file: str, index: int, provider_default: str) -> dict:
    provider = guess_provider(record, provider_default)
    source_url = first_nonblank(record.get('source_url'), record.get('website'), record.get('url'), record.get('link'), record.get('maps_url'))
    title = first_nonblank(record.get('source_title'), record.get('title'), record.get('name'), record.get('raw_name'))
    query_id = first_nonblank(record.get('provider_query_id'), record.get('discovery_prompt_id'), record.get('source_name'), record.get('query_id'), record.get('query'))
    query_text = first_nonblank(record.get('provider_query_text'), record.get('discovery_prompt'), record.get('query'), record.get('source_query'), record.get('search_query'))
    rank = raw_rank(record)
    legacy_id = first_nonblank(record.get('source_record_id'), record.get('legacy_source_record_id'), record.get('id'))
    obs_id = stable_id('obs', provider, source_url, query_id, title, index)
    content_text = first_nonblank(record.get('raw_content'), record.get('evidence_text'), record.get('description'), record.get('source_snippet'), record.get('content'))
    content_path, content_sha, content_id = write_content(run_dir, obs_id, content_text)
    raw_path, raw_sha = write_raw_payload(run_dir, obs_id, record)
    website_url = first_nonblank(record.get('website_url'), record.get('website'))
    specific_rental_page_url = first_nonblank(record.get('specific_rental_page_url'), record.get('rental_page_url'))
    if not specific_rental_page_url:
        rental_terms = ['location', 'louer', 'salle', 'privatisation', 'reservation', 'réservation']
        low_url = source_url.lower()
        low_title = title.lower()
        if any(t in low_url or t in low_title for t in rental_terms):
            specific_rental_page_url = source_url
    provider_extra = {}
    for k in ('source_type', 'source_confidence', 'formal_extraction_status', 'is_aggregator', 'aggregator_domain', 'rental_possible_status'):
        if k in record and not blank(record.get(k)):
            provider_extra[k] = record.get(k)
    return {
        'schema_version': SCHEMA_VERSION,
        'observation_id': obs_id,
        'run_id': run_id,
        'provider': provider,
        'provider_query_id': query_id,
        'provider_query_text': query_text,
        'provider_rank': rank,
        'provider_score': record.get('provider_score', ''),
        'discovered_at': first_nonblank(record.get('discovered_at'), record.get('collected_at'), record.get('last_seen_at'), now_iso()),
        'source_url': source_url,
        'source_domain': first_nonblank(record.get('source_domain'), safe_domain(source_url), safe_domain(website_url)),
        'source_title': title,
        'source_snippet': first_nonblank(record.get('source_snippet'), record.get('description'), record.get('evidence_text'), record.get('content'))[:1500],
        'website_url': website_url,
        'specific_rental_page_url': specific_rental_page_url,
        'candidate_name_hint': first_nonblank(record.get('candidate_name_hint'), record.get('raw_name'), record.get('name'), record.get('title')),
        'candidate_address_hint': first_nonblank(record.get('candidate_address_hint'), record.get('raw_address'), record.get('address')),
        'candidate_city_hint': first_nonblank(record.get('candidate_city_hint'), record.get('raw_city'), record.get('city')),
        'candidate_department_hint': first_nonblank(record.get('candidate_department_hint'), record.get('department'), record.get('raw_department')),
        'candidate_lat_hint': record.get('lat', record.get('latitude', '')),
        'candidate_lon_hint': record.get('lon', record.get('lng', record.get('longitude', ''))),
        'place_id': first_nonblank(record.get('place_id'), record.get('google_place_id')),
        'osm_id': first_nonblank(record.get('osm_id'), record.get('osm_type_id')),
        'maps_url': first_nonblank(record.get('maps_url'), record.get('google_maps_url')),
        'raw_payload_path': raw_path,
        'raw_payload_sha256': raw_sha,
        'content_path': content_path,
        'content_sha256': content_sha,
        'content_id': content_id,
        'legacy_source_record_id': legacy_id,
        'source_file': source_file,
        'provider_extra': provider_extra,
    }


def evidence_row(obs: dict, record: dict, field_name: str, value: str, method: str, confidence: float, quote: str = '') -> dict:
    value = as_str(value).strip()
    fe_id = stable_id('fe', obs['observation_id'], field_name, value[:120])
    return {
        'schema_version': SCHEMA_VERSION,
        'field_evidence_id': fe_id,
        'venue_entity_id': '',
        'observation_id': obs['observation_id'],
        'content_id': obs.get('content_id', ''),
        'field_name': field_name,
        'value_raw': value,
        'value_structured': None,
        'evidence_quote': quote or value,
        'evidence_url': obs.get('specific_rental_page_url') or obs.get('source_url') or obs.get('website_url') or '',
        'source_type': as_str(record.get('source_type') or record.get('provider') or obs.get('provider')),
        'extraction_method': method,
        'confidence': confidence,
        'extracted_at': now_iso(),
    }


def evidence_from_record(obs: dict, record: dict) -> list[dict]:
    rows = []
    candidates = [
        ('address', first_nonblank(record.get('raw_address'), record.get('address'), record.get('formal_address_source')), 'legacy_import', 0.55),
        ('contact', first_nonblank(record.get('raw_contact'), record.get('contact'), record.get('formal_contact_source'), record.get('email'), record.get('phone')), 'legacy_import', 0.55),
        ('price', first_nonblank(record.get('raw_price'), record.get('price_text'), record.get('formal_price_source')), 'legacy_import', 0.45),
        ('capacity', first_nonblank(record.get('raw_capacity'), record.get('capacity_text'), record.get('formal_capacity_source')), 'legacy_import', 0.45),
        ('rental_possible', first_nonblank(record.get('rental_possible_status'), record.get('rental_positive_signals'), record.get('rental_email_question')), 'rules', 0.50),
        ('website', first_nonblank(obs.get('website_url')), 'provider_or_legacy', 0.50),
        ('specific_rental_page', first_nonblank(obs.get('specific_rental_page_url')), 'rules', 0.45),
    ]
    for field, value, method, conf in candidates:
        if not blank(value):
            quote = ''
            if field == 'rental_possible':
                quote = first_nonblank(record.get('rental_positive_signals'), record.get('rental_negative_signals'), value)
            rows.append(evidence_row(obs, record, field, value, method, conf, quote))
    return rows


def provider_from_path(path: Path) -> str:
    name = path.name.lower()
    if 'tavily' in name:
        return 'tavily'
    if 'google_places' in name or 'places' in name:
        return 'google_places'
    if 'google_search' in name:
        return 'google_search'
    if 'osm' in name or 'overpass' in name:
        return 'osm'
    return 'legacy_source_records'


def build_run(input_paths: list[Path], run_id: str, output_root: Path) -> dict:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    observations = []
    field_evidence = []
    malformed = []
    url_seen = defaultdict(list)

    for path in input_paths:
        records = read_records(path)
        provider_default = provider_from_path(path)
        for i, rec in enumerate(records, 1):
            try:
                obs = observation_from_record(rec, run_id, run_dir, str(path), i, provider_default)
                if blank(obs.get('source_url')):
                    malformed.append({'source_file': str(path), 'index': i, 'reason': 'missing_source_url'})
                    continue
                observations.append(obs)
                url_seen[normalize_url(obs['source_url']).lower()].append(obs['observation_id'])
                field_evidence.extend(evidence_from_record(obs, rec))
            except Exception as e:
                malformed.append({'source_file': str(path), 'index': i, 'reason': str(e)})

    duplicate_url_groups = {url: ids for url, ids in url_seen.items() if url and len(ids) > 1}
    (run_dir / 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
    (run_dir / 'field_evidence.json').write_text(json.dumps(field_evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    converted = {'inputs': [str(p) for p in input_paths], 'observation_ids': [o['observation_id'] for o in observations]}
    (run_dir / 'converted_from_source_records.json').write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding='utf-8')

    report = {
        'generated_at': now_iso(),
        'run_id': run_id,
        'input_files': [str(p) for p in input_paths],
        'observations': len(observations),
        'field_evidence': len(field_evidence),
        'malformed': len(malformed),
        'malformed_examples': malformed[:20],
        'observations_by_provider': dict(Counter(o['provider'] for o in observations)),
        'observations_with_url': sum(1 for o in observations if not blank(o.get('source_url'))),
        'observations_with_query': sum(1 for o in observations if not blank(o.get('provider_query_text') or o.get('provider_query_id'))),
        'observations_with_content_hash': sum(1 for o in observations if not blank(o.get('content_sha256'))),
        'field_evidence_by_field': dict(Counter(e['field_name'] for e in field_evidence)),
        'duplicate_url_groups_preserved': len(duplicate_url_groups),
        'duplicate_observations_preserved': sum(len(v) for v in duplicate_url_groups.values()),
        'outputs': {
            'run_dir': str(run_dir),
            'observations': str(run_dir / 'observations.json'),
            'field_evidence': str(run_dir / 'field_evidence.json'),
            'report': str(run_dir / 'report.json'),
        },
    }
    (run_dir / 'duplicate_url_groups.json').write_text(json.dumps(duplicate_url_groups, ensure_ascii=False, indent=2), encoding='utf-8')
    (run_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description='Build a non-destructive discovery run with common source_observations + field_evidence lineage.')
    ap.add_argument('inputs', nargs='+', help='Source record JSON/CSV files from Tavily, Google, Places, OSM, legacy runs, etc.')
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--output-root', default=str(ROOT / 'data/discovery_runs'))
    args = ap.parse_args()
    report = build_run([Path(p) for p in args.inputs], args.run_id, Path(args.output_root))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
