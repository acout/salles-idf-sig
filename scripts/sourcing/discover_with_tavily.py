#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from common import ROOT, now_iso

for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
    os.environ.pop(_k, None)

TAVILY_SEARCH_URL = 'https://api.tavily.com/search'


def load_key(path: str | None) -> str:
    if os.getenv('TAVILY_API_KEY'):
        return os.environ['TAVILY_API_KEY'].strip()
    p = Path(path or (Path.home() / '.hermes/secrets-tmp/tavily-api-key.txt'))
    return p.read_text(encoding='utf-8').strip()


def post_json(url: str, payload: dict, timeout: int = 45) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')[:1200]
        raise RuntimeError(f'Tavily HTTP {e.code}: {detail}') from e


def tavily_search(api_key: str, prompt: str, max_results: int, include_raw_content: bool) -> dict:
    payload = {
        'api_key': api_key,
        'query': prompt,
        'search_depth': 'advanced',
        'max_results': max_results,
        'include_answer': False,
        'include_images': False,
        'include_raw_content': include_raw_content,
    }
    return post_json(TAVILY_SEARCH_URL, payload)


def result_to_source_record(result: dict, prompt: str, prompt_id: str, rank: int, run_id: str) -> dict:
    url = result.get('url') or ''
    title = result.get('title') or ''
    content = result.get('content') or ''
    raw_content = result.get('raw_content') or ''
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace('www.', '').lower()
    return {
        'name': title[:180],
        'title': title,
        'website': url,
        'source_url': url,
        'source_domain': domain,
        'source_type': 'tavily_prompt_search',
        'source_confidence': 'medium',
        'provider': 'tavily',
        'provider_score': result.get('score', ''),
        'provider_rank': rank,
        'discovery_prompt_id': prompt_id,
        'discovery_prompt': prompt,
        'description': content[:1500],
        'evidence_text': (raw_content or content)[:2500],
        'raw_content': raw_content[:12000] if raw_content else '',
        'target_run': run_id,
        'discovered_at': now_iso(),
    }


def load_prompts(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, list):
        out = []
        for i, item in enumerate(data, 1):
            if isinstance(item, str):
                out.append({'id': f'p{i:02d}', 'prompt': item})
            else:
                out.append({'id': item.get('id') or f'p{i:02d}', 'prompt': item['prompt']})
        return out
    return [{'id': k, 'prompt': v} for k, v in data.items()]


def main() -> None:
    ap = argparse.ArgumentParser(description='Discover venue candidate URLs with Tavily using natural-language prompts.')
    ap.add_argument('--prompts', required=True, help='JSON list/dict of natural-language prompts')
    ap.add_argument('--output', required=True)
    ap.add_argument('--report', default='')
    ap.add_argument('--run-id', default=now_iso()[:10].replace('-', '') + '_tavily')
    ap.add_argument('--max-results', type=int, default=8)
    ap.add_argument('--include-raw-content', action='store_true')
    ap.add_argument('--dedupe-urls', action='store_true', help='Collapse duplicate URLs. Default preserves repeated URLs across prompts to keep discovery lineage.')
    ap.add_argument('--key-file', default='')
    ap.add_argument('--sleep', type=float, default=0.2)
    args = ap.parse_args()

    api_key = load_key(args.key_file or None)
    prompts = load_prompts(Path(args.prompts))
    records = []
    raw_results = []
    errors = []

    for item in prompts:
        pid, prompt = item['id'], item['prompt']
        try:
            res = tavily_search(api_key, prompt, args.max_results, args.include_raw_content)
            raw_results.append({'prompt_id': pid, 'prompt': prompt, 'response': res})
            for rank, result in enumerate(res.get('results') or [], 1):
                records.append(result_to_source_record(result, prompt, pid, rank, args.run_id))
        except Exception as e:
            errors.append({'prompt_id': pid, 'prompt': prompt, 'error': str(e)})
        time.sleep(args.sleep)

    # Preserve repeated URLs across prompts by default: query/rank/provider-score lineage is useful.
    deduped = []
    seen = set()
    duplicates = 0
    if args.dedupe_urls:
        for rec in records:
            key = (rec.get('source_url') or '').split('#')[0].rstrip('/').lower()
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(rec)
    else:
        deduped = records
        for rec in records:
            key = (rec.get('source_url') or '').split('#')[0].rstrip('/').lower()
            if key in seen:
                duplicates += 1
            seen.add(key)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {
        'generated_at': now_iso(),
        'provider': 'tavily',
        'run_id': args.run_id,
        'prompts': len(prompts),
        'raw_results': len(records),
        'output_records': len(deduped),
        'duplicate_urls_detected': duplicates,
        'duplicate_urls_removed': duplicates if args.dedupe_urls else 0,
        'dedupe_urls': bool(args.dedupe_urls),
        'errors': errors,
        'output': str(output),
    }
    report_path = Path(args.report) if args.report else output.with_suffix('.report.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    raw_path = output.with_suffix('.raw.json')
    raw_path.write_text(json.dumps(raw_results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
