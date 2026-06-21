#!/usr/bin/env python3
"""Standalone runner for AI field interpretation batches.

Reads prepared batch JSON files, calls web_extract on each URL,
and writes field_interpret_results_*.jsonl.
Designed to be run via terminal background process.
"""
from __future__ import annotations
import json, sys, time, re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'data/discovery_runs/ai_field_interpretation_20260621'

# --- Regex patterns (same as hermes_web_extract_field_interpret.py) ---
PHONE_RE = re.compile(r'(?:(?:\+33|0)\s*[1-9](?:[\s.\-]*\d{2}){4})')
EMAIL_RE = re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I)
POSTAL_RE = re.compile(r'\b(75\d{3}|77\d{3}|78\d{3}|91\d{3}|92\d{3}|93\d{3}|94\d{3}|95\d{3})\b')
PRICE_PATTERNS = [re.compile(p, re.I) for p in [
    r'(?:€|eur(?:os?)?)\s?\d+[\d,.]*(?:\s?(?:/|par)\s?(?:h|heure|hour|jour|day|demi-journée))?',
    r'\d+[\d,.]*\s?(?:€|eur(?:os?)?)(?:\s?(?:/|par)\s?(?:h|heure|hour|jour|day|demi-journée))?',
    r'(?:per hour|par heure|à l.?heure|hourly)[^\n\.]{0,60}?(?:€\s?\d+[\d,.]*|\d+[\d,.]*\s?€)',
    r'(?:per day|par jour|daily|journée)[^\n\.]{0,60}?(?:€\s?\d+[\d,.]*|\d+[\d,.]*\s?€)',
    r'(?:minimum booking fee|frais minimum|minimum)[^\n\.]{0,80}?(?:€\s?\d+[\d,.]*|\d+[\d,.]*\s?€)',
]]
CAP_PATTERNS = [re.compile(p, re.I) for p in [
    r'\b\d+\s?[-–]\s?\d+\s?(?:people|personnes|pers\.?|participants?)\b',
    r'\b(?:jusqu(?:’|\'|e)?à|up to|capacity|capacité)[^\n\.]{0,60}?\d+\s?(?:people|personnes|pers\.?|participants?)?',
    r'\b\d+\s?(?:people|personnes|pers\.?|participants?)\b',
]]
SURF_PATTERNS = [re.compile(r'\b\d+[\d,.]*\s?(?:m²|m2|sqm|square meters?)\b', re.I)]

CUT_MARKERS = [
    "## Other Space in the Same Venue", "## Other Spaces in the Same Venue",
    "## Suggested Alternatives", "## Similar spaces", "## Similar Spaces",
    "# Similar spaces", "### Suggested Alternatives",
]


def compact(s): return re.sub(r'\s+', ' ', s or '').strip()

def snippets(content, patterns, limit=5):
    out = []
    for pat in patterns:
        for m in pat.finditer(content or ''):
            txt = compact(m.group(0))
            if txt and txt not in out: out.append(txt)
            if len(out) >= limit: return out
    return out

def capacity_max_from_text(text):
    no_surface = re.sub(r'\b\d+[\d,.]*\s?(?:m²|m2|sqm|square meters?)\b', ' ', text or '', flags=re.I)
    ranges = []
    for m in re.finditer(r'\b(\d+)\s?[-–]\s?(\d+)\s?(?:people|personnes|pers\.?|participants?)', no_surface, re.I):
        ranges.append(int(m.group(2)))
    if ranges: return max(n for n in ranges if 0 < n < 1000)
    nums = []
    for m in re.finditer(r'\b(?:jusqu(?:’|\'|e)?à|up to|capacity|capacité)[^\n\.]{0,50}?(\d+)\s?(?:people|personnes|pers\.?|participants?)?', no_surface, re.I):
        nums.append(int(m.group(1)))
    for m in re.finditer(r'\b(\d+)\s?(?:people|personnes|pers\.?|participants?)\b', no_surface, re.I):
        nums.append(int(m.group(1)))
    nums = [n for n in nums if 0 < n < 1000]
    return max(nums) if nums else 0

def surface_from_text(text):
    m = re.search(r'\b(\d+[\d,.]*)\s?(?:m²|m2|sqm|square meters?)\b', text or '', re.I)
    return str(int(float(m.group(1).replace(',','.')))) if m else ''

def relevant_content(task, content):
    text = content or ''
    lower = text.lower()
    positions = [lower.find(m.lower()) for m in CUT_MARKERS if lower.find(m.lower()) != -1]
    if positions: text = text[:min(positions)]
    return text

def infer_address(content):
    for line in (content or '').splitlines():
        l = compact(line); ll = l.lower()
        if not l or len(l) > 180: continue
        if any(k in ll for k in ['address:', 'adresse', 'location:', 'lieu:', 'source :', 'source:']):
            if POSTAL_RE.search(l) or any(c in ll for c in ['paris','gentilly','montrouge','fontenay','chevilly','charenton','meudon','orly','rungis']):
                return l.replace('**','').replace('- ','').strip()
    return ''

def normalize_capacity_display(text):
    raw = text or ''
    ranges = [compact(m.group(0)) for m in re.finditer(r'\b\d+\s?[-–]\s?\d+\s?(?:people|personnes|pers\.?|participants?)\b', raw, re.I)]
    surfaces = [compact(m.group(0)) for m in re.finditer(r'\b\d+[\d,.]*\s?(?:m²|m2|sqm|square meters?)\b', raw, re.I)]
    if ranges: return '; '.join(dict.fromkeys(ranges + surfaces))
    return compact(raw)


def interpret(task, content, error=None):
    content = relevant_content(task, content)
    cap = snippets(content, CAP_PATTERNS, 3)
    surf = snippets(content, SURF_PATTERNS, 2)
    price = snippets(content, PRICE_PATTERNS, 5)
    emails = list(dict.fromkeys(EMAIL_RE.findall(content or '')))[:3]
    phones = list(dict.fromkeys(PHONE_RE.findall(content or '')))[:3]
    pc = POSTAL_RE.search(content or '')
    captext = normalize_capacity_display('; '.join(dict.fromkeys(cap + surf)))
    pricet = '; '.join(price)
    surf_m2 = surface_from_text(' '.join(surf))
    lower = (content or '').lower()
    fields = {
        'capacity_text': captext,
        'capacity_max_detected': capacity_max_from_text(captext),
        'surface_m2': surf_m2,
        'price_text': pricet,
        'contact': ' — '.join(phones + emails),
        'address': infer_address(content),
        'city': task.get('city') or '',
        'postal_code': pc.group(1) if pc else '',
        'specific_rental_page_url': (task.get('current') or {}).get('specific_rental_page_url') or task.get('url'),
        'rental_possible_status': 'possible' if any(k in lower for k in ['book','booking','location','privatisation','rent','louer']) else '',
        'pros': '',
        'cons': 'Disponibilité à confirmer' if any(k in lower for k in ['unavailable','currently unavailable','uncertain availability','indisponible']) else '',
    }
    evidence = {
        'capacity_text': '; '.join((cap + surf)[:4]),
        'price_text': '; '.join(price[:4]),
        'contact': fields['contact'],
        'address': fields['address'],
        'specific_rental_page_url': task.get('url'),
    }
    confidence = {
        'capacity_text': 0.85 if captext else 0.0,
        'price_text': 0.85 if pricet else 0.0,
        'contact': 0.8 if fields['contact'] else 0.0,
        'address': 0.65 if fields['address'] else 0.0,
        'specific_rental_page_url': 0.9 if fields['specific_rental_page_url'] else 0.0,
    }
    return {
        'candidate_id': task.get('candidate_id'), 'name': task.get('name'), 'url': task.get('url'),
        'success': bool(content) and not error,
        'fields': fields, 'evidence': evidence, 'confidence': confidence,
        'interpretation_reason': 'AI page summary read via web_extract; field interpretation with relevant_content cropping and capacity normalization.' if content else f'web_extract failed: {error}',
        'page_content_length': len(content or ''),
    }


if __name__ == '__main__':
    import urllib.request, urllib.parse, json
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    API_KEY = Path('/home/antho/.hermes/secrets-tmp/tavily-api-key.txt').read_text().strip()
    TOTAL = 0
    for bi in range(start, end + 1):
        inp = BASE / f'field_interpret_batch_{bi:02d}.json'
        out = BASE / f'field_interpret_results_{bi:02d}.jsonl'
        if not inp.exists():
            print(f'SKIP {inp.name} (not found)')
            continue
        tasks = json.loads(inp.read_text(encoding='utf-8'))
        rows = []
        for i in range(0, len(tasks), 5):
            chunk = tasks[i:i+5]
            urls = [t['url'] for t in chunk]
            # Use Tavily extract API directly
            all_content = {}
            for url in urls:
                try:
                    req_data = json.dumps({"urls": [url], "api_key": API_KEY}).encode()
                    req = urllib.request.Request("https://api.tavily.com/extract", data=req_data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = json.loads(resp.read())
                        results = data.get("results", [])
                        all_content[url] = results[0].get("raw_content", results[0].get("text", "")) if results else ""
                except Exception as e:
                    all_content[url] = ""
                    print(f'  ERR {url[:60]}: {e}')
            
            for task in chunk:
                content = all_content.get(task['url'], '')
                rows.append(json.dumps(interpret(task, content), ensure_ascii=False))
            
            TOTAL += len(chunk)
            if TOTAL % 25 == 0:
                print(f'  Progress: batch {bi}, {TOTAL} tasks done')
        
        out.write_text('\n'.join(rows) + '\n', encoding='utf-8')
        print(f'BATCH {bi:02d}: {len(rows)} results written to {out.name}')
    
    print(f'DONE. Total tasks processed: {TOTAL}')