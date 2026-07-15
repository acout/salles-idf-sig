#!/usr/bin/env python3
"""Hermes-run AI field interpreter using web_extract page summaries.

This script is intended to be executed inside Hermes `execute_code` or another
Hermes runtime where `hermes_tools.web_extract` is available. It reads prepared
batch JSON files and writes one JSONL interpretation per candidate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from hermes_tools import web_extract
except Exception:  # pragma: no cover - only available in Hermes execute_code
    web_extract = None

ROOT = Path('/home/antho/salles-idf-sig')
BASE = ROOT / 'data/discovery_runs/ai_field_interpretation_20260621'

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


def compact(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()


def snippets(content: str, patterns: list[re.Pattern], limit: int = 5) -> list[str]:
    out: list[str] = []
    for pat in patterns:
        for m in pat.finditer(content or ''):
            txt = compact(m.group(0))
            if txt and txt not in out:
                out.append(txt)
            if len(out) >= limit:
                return out
    return out


def capmax(text: str) -> int:
    nums = [int(x) for x in re.findall(r'\b\d+\b', text or '') if 0 < int(x) < 10000]
    return max(nums) if nums else 0


def surface(text: str) -> str:
    m = re.search(r'\b(\d+[\d,.]*)\s?(?:m²|m2|sqm|square meters?)\b', text or '', re.I)
    return str(int(float(m.group(1).replace(',', '.')))) if m else ''


def infer_address(content: str) -> str:
    for line in (content or '').splitlines():
        l = compact(line)
        ll = l.lower()
        if not l or len(l) > 180:
            continue
        if any(k in ll for k in ['address:', 'adresse', 'location:', 'lieu:', 'source :', 'source:']):
            if POSTAL_RE.search(l) or any(c in ll for c in ['paris', 'gentilly', 'montrouge', 'fontenay', 'chevilly', 'charenton', 'meudon', 'orly', 'rungis']):
                return l.replace('**', '').replace('- ', '').strip()
    return ''


def relevant_content(task: dict[str, Any], content: str) -> str:
    """Keep the part of an AI page summary most likely to describe THIS venue.

    Aggregators and marketplaces often append alternatives/similar spaces. Those
    sections contain valid capacities/prices, but for other venues. Crop them out
    before field interpretation.
    """
    text = content or ""
    cut_markers = [
        "## Other Space in the Same Venue",
        "## Other Spaces in the Same Venue",
        "## Suggested Alternatives",
        "## Similar spaces",
        "## Similar Spaces",
        "# Similar spaces",
        "### Suggested Alternatives",
    ]
    lower = text.lower()
    cut_positions = [lower.find(m.lower()) for m in cut_markers if lower.find(m.lower()) != -1]
    if cut_positions:
        text = text[: min(cut_positions)]
    return text


def interpret(task: dict[str, Any], content: str, error: str | None = None) -> dict[str, Any]:
    content = relevant_content(task, content)
    cap = snippets(content, CAP_PATTERNS, 3)
    surf = snippets(content, SURF_PATTERNS, 2)
    price = snippets(content, PRICE_PATTERNS, 5)
    emails = list(dict.fromkeys(EMAIL_RE.findall(content or '')))[:3]
    phones = list(dict.fromkeys(PHONE_RE.findall(content or '')))[:3]
    pc = POSTAL_RE.search(content or '')
    captext = '; '.join(dict.fromkeys(cap + surf))
    pricet = '; '.join(price)
    surf_m2 = surface(' '.join(surf))
    lower = (content or '').lower()
    fields = {
        'capacity_text': captext,
        'capacity_max_detected': capmax(captext),
        'surface_m2': surf_m2,
        'price_text': pricet,
        'contact': ' — '.join(phones + emails),
        'address': infer_address(content),
        'city': task.get('city') or '',
        'postal_code': pc.group(1) if pc else '',
        'specific_rental_page_url': (task.get('current') or {}).get('specific_rental_page_url') or task.get('url'),
        'rental_possible_status': 'possible' if any(k in lower for k in ['book', 'booking', 'location', 'privatisation', 'rent', 'louer']) else '',
        'pros': '',
        'cons': 'Disponibilité à confirmer' if any(k in lower for k in ['unavailable', 'currently unavailable', 'uncertain availability', 'indisponible']) else '',
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
        'candidate_id': task.get('candidate_id'),
        'name': task.get('name'),
        'url': task.get('url'),
        'success': bool(content) and not error,
        'fields': fields,
        'evidence': evidence,
        'confidence': confidence,
        'interpretation_reason': 'AI page summary read via web_extract; structured field interpretation from explicit page text.' if content else f'web_extract failed: {error}',
        'page_content_length': len(content or ''),
    }


def run_batches(start: int, end: int) -> list[tuple[int, int]]:
    if web_extract is None:
        raise RuntimeError('hermes_tools.web_extract is not available; run through Hermes execute_code')
    made: list[tuple[int, int]] = []
    for bi in range(start, end + 1):
        inp = BASE / f'field_interpret_batch_{bi:02d}.json'
        if not inp.exists():
            continue
        tasks = json.loads(inp.read_text(encoding='utf-8'))
        rows = []
        for i in range(0, len(tasks), 5):
            chunk = tasks[i:i + 5]
            res = web_extract([t['url'] for t in chunk])
            by_url = {r.get('url'): r for r in res.get('results', [])}
            for task in chunk:
                r = by_url.get(task['url'], {})
                rows.append(json.dumps(interpret(task, r.get('content') or '', r.get('error')), ensure_ascii=False))
        out = BASE / f'field_interpret_results_{bi:02d}.jsonl'
        out.write_text('\n'.join(rows) + '\n', encoding='utf-8')
        made.append((bi, len(rows)))
    return made
