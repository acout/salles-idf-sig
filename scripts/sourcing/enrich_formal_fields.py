#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from common import ROOT, now_iso

for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
    os.environ.pop(_k, None)

AGGREGATOR_DOMAINS = {
    '1001salles.com', 'abcsalles.com', 'privateaser.com', 'pagesjaunes.fr', 'yelp.com', 'm.yelp.com',
    'sallesdesfetes.fr', 'salle-des-fetes.com', 'louerunesalle.com', 'directsalles.com', 'aleou.fr',
    'meetingbooker.com', 'bizmeeting.com', 'snapevent.fr', 'kactus.com', 'funbooker.com', 'peerspace.com',
    'jemepropose.com', 'starofservice.com', 'koifaire.com', 'ville-data.com', 'annuaire-entreprises.data.gouv.fr',
    'cours-de-yoga.fr', 'superprof.fr', 'spectable.com', 'justacote.com', 'eventdrive.com'
}
AGGREGATOR_PATH_HINTS = (
    'annuaire', 'search', 'location-de-salle', 'location-de-salles', 'salle-a-louer', 'salles-de-',
    'departement', 'near', 'recherche', 'listing', 'location-salle', 'lieux', 'venue-finder'
)
VENUE_WORDS = ('studio', 'danse', 'dojo', 'yoga', 'mjc', 'association', 'centre', 'theatre', 'théâtre', 'repetition', 'répétition', 'salle', 'espace')
BAD_CHILD_WORDS = ('login', 'signin', 'facebook', 'instagram', 'twitter', 'linkedin', 'mailto:', 'tel:', 'cookie', 'privacy', 'mentions')

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
PHONE_RE = re.compile(r'(?:(?:\+33|0)\s?[1-9](?:[\s.\-]?\d{2}){4})')
PRICE_RE = re.compile(r'(?:\b\d{1,4}\s?(?:€|eur|euro)s?\s?(?:/|par)?\s?(?:h|heure|heures|journée|jour|demi-journée|mois|stage|personne|pers)?\b|à partir de\s+\d{1,4}\s?€|dès\s+\d{1,4}\s?€)', re.I)
CAPACITY_RE = re.compile(r'(?:\b\d{1,4}\s?(?:m²|m2|personnes|pers\.?|participants|places|pax)\b|capacité\s*:?\s*\d{1,4})', re.I)
ADDRESS_RE = re.compile(r'\b\d{1,4}\s+(?:rue|avenue|av\.?|boulevard|bd|place|passage|impasse|allée|allee|quai|route|chemin|cours|villa|square)\s+[^\n<>;,]{3,90}', re.I)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
LINK_RE = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r'<[^>]+>')
SPACE_RE = re.compile(r'\s+')


def domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().replace('www.', '')
    except Exception:
        return ''


def is_aggregator(record: dict) -> tuple[bool, str]:
    url = record.get('source_url') or record.get('website') or ''
    d = domain(url)
    path = urllib.parse.urlparse(url).path.lower() if url else ''
    text = ' '.join(str(record.get(k, '')) for k in ('name', 'description', 'evidence_text', 'category')).lower()
    if d in AGGREGATOR_DOMAINS:
        return True, d
    if any(h in path for h in AGGREGATOR_PATH_HINTS) and not any(v in d for v in ('ville-', 'paris.fr')):
        return True, d or 'path_hint'
    if any(w in text for w in ('pages jaunes', 'abc salles', '1001 salles', 'privateaser', 'yelp', 'annuaire', 'liste des')):
        return True, d or 'text_hint'
    return False, d


def fetch(url: str, timeout=7) -> tuple[int, str, str]:
    if not url or not url.startswith(('http://', 'https://')):
        return 0, '', 'invalid_url'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 Hermes salles-idf-sig formal-enrichment/1.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.6',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get('content-type', '')
            raw = r.read(900_000)
            enc = r.headers.get_content_charset() or 'utf-8'
            return r.status, raw.decode(enc, errors='replace'), ctype
    except Exception as e:
        return 0, '', type(e).__name__


def strip_tags(s: str) -> str:
    return SPACE_RE.sub(' ', html.unescape(TAG_RE.sub(' ', s or ''))).strip()


def uniq(xs, limit=8):
    out = []
    seen = set()
    for x in xs:
        x = SPACE_RE.sub(' ', html.unescape(str(x))).strip(' .;,-\n\t')
        if not x:
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
        if len(out) >= limit:
            break
    return out


def extract_formal(html_text: str) -> dict:
    text = strip_tags(html_text)
    title = ''
    m = TITLE_RE.search(html_text or '')
    if m:
        title = strip_tags(m.group(1))[:160]
    emails = uniq(EMAIL_RE.findall(text), 5)
    phones = uniq(PHONE_RE.findall(text), 5)
    prices = uniq([m.group(0) for m in PRICE_RE.finditer(text)], 8)
    capacities = uniq([m.group(0) for m in CAPACITY_RE.finditer(text)], 8)
    addresses = uniq([m.group(0) for m in ADDRESS_RE.finditer(text)], 5)
    return {
        'page_title': title,
        'emails': emails,
        'phones': phones,
        'prices': prices,
        'capacities': capacities,
        'addresses': addresses,
        'text_sample': text[:900],
    }


def extract_child_links(html_text: str, base_url: str, city: str, max_links=12) -> list[dict]:
    links = []
    base_domain = domain(base_url)
    for href, label_html in LINK_RE.findall(html_text or ''):
        label = strip_tags(label_html)
        if not label or len(label) < 4:
            continue
        abs_url = urllib.parse.urljoin(base_url, href)
        low = (abs_url + ' ' + label).lower()
        if any(b in low for b in BAD_CHILD_WORDS):
            continue
        if not any(w in low for w in VENUE_WORDS):
            continue
        d = domain(abs_url)
        # keep same-domain detail links and explicit source links; avoid generic pagination/filter URLs
        if base_domain and d and d != base_domain and d in AGGREGATOR_DOMAINS:
            continue
        path = urllib.parse.urlparse(abs_url).path
        if len(path) < 2 or path in ('/', ''):
            continue
        if any(x in low for x in ('?page=', '#', 'tri=', 'filtre=', 'cookie')):
            continue
        links.append({'name': label[:140], 'source_url': abs_url, 'website': abs_url, 'city': city})
    # dedupe by URL/name
    out = []
    seen = set()
    for l in links:
        k = (l['source_url'].split('#')[0].rstrip('/'), l['name'].lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(l)
        if len(out) >= max_links:
            break
    return out


def enrich_record(record: dict, expand_aggregators=True) -> dict:
    rec = dict(record)
    url = rec.get('source_url') or rec.get('website') or ''
    agg, agg_domain = is_aggregator(rec)
    rec['is_aggregator'] = 'yes' if agg else 'no'
    rec['aggregator_domain'] = agg_domain
    rec['formal_scrape_checked_at'] = now_iso()
    status, body, ctype = fetch(url)
    rec['formal_scrape_http_status'] = str(status) if status else ''
    rec['formal_scrape_content_type'] = ctype
    children = []
    if not body:
        rec['formal_extraction_status'] = 'fetch_failed'
    else:
        ex = extract_formal(body)
        rec['formal_page_title'] = ex['page_title']
        if not rec.get('contact'):
            contact = '; '.join(ex['emails'] + ex['phones'])
            if contact:
                rec['contact'] = contact
                rec['formal_contact_source'] = 'scraped_page'
        if not rec.get('price_text') and ex['prices']:
            rec['price_text'] = '; '.join(ex['prices'][:4])
            rec['formal_price_source'] = 'scraped_page'
        if not rec.get('capacity_text') and ex['capacities']:
            rec['capacity_text'] = '; '.join(ex['capacities'][:4])
            rec['formal_capacity_source'] = 'scraped_page'
        if not rec.get('address') and ex['addresses']:
            rec['address'] = ex['addresses'][0]
            rec['formal_address_source'] = 'scraped_page'
        rec['formal_evidence_text'] = ex['text_sample']
        rec['formal_extraction_status'] = 'scraped'
        if agg and expand_aggregators:
            children = extract_child_links(body, url, rec.get('city', ''))
            rec['aggregator_child_links_count'] = str(len(children))
        else:
            rec['aggregator_child_links_count'] = '0'
    missing = []
    if not rec.get('address'):
        missing.append('adresse précise')
    if not rec.get('contact'):
        missing.append('contact')
    if not rec.get('price_text'):
        missing.append('prix')
    if not rec.get('capacity_text'):
        missing.append('capacité')
    rec['missing_formal_fields'] = ', '.join(missing)
    rec['email_questions'] = '; '.join(f'Confirmer {x}' for x in missing) if missing else 'Aucun champ formel manquant détecté'
    rec['formal_completeness_score'] = str(4 - len(missing))
    return {'record': rec, 'children': children}


def child_to_record(child: dict, parent: dict) -> dict:
    r = dict(child)
    r.update({
        'department': parent.get('department') or '',
        'source_type': 'aggregator_child_link',
        'source_confidence': 'low',
        'description': f"Lien extrait depuis agrégateur {parent.get('source_url')}: {parent.get('name')}",
        'evidence_text': f"Lien enfant extrait depuis agrégateur: {parent.get('source_url')}",
        'parent_aggregator_url': parent.get('source_url') or parent.get('website') or '',
        'parent_aggregator_name': parent.get('name') or '',
        'is_aggregator': 'no',
        'aggregator_domain': '',
        'target_run': parent.get('target_run') or 'formal_enrichment',
    })
    return r


def main():
    ap = argparse.ArgumentParser(description='Scrape formal fields and mark/expand aggregator records.')
    ap.add_argument('input')
    ap.add_argument('--output', default=str(ROOT / 'data/source_records/enriched_formal_source_records.json'))
    ap.add_argument('--report', default='')
    ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--no-expand-aggregators', action='store_true')
    args = ap.parse_args()

    records = json.loads(Path(args.input).read_text(encoding='utf-8'))
    if args.limit:
        records = records[:args.limit]
    started = time.time()
    enriched = []
    child_records = []

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(enrich_record, r, not args.no_expand_aggregators) for r in records]
        for fut in cf.as_completed(futures):
            res = fut.result()
            rec = res['record']
            enriched.append(rec)
            for child in res['children']:
                child_records.append(child_to_record(child, rec))

    # Deduplicate child records against existing urls/names.
    existing_keys = {(str(r.get('source_url') or '').lower().rstrip('/'), str(r.get('name') or '').lower()) for r in enriched}
    dedup_children = []
    for c in child_records:
        key = (str(c.get('source_url') or '').lower().rstrip('/'), str(c.get('name') or '').lower())
        if key in existing_keys:
            continue
        existing_keys.add(key)
        dedup_children.append(c)

    combined = enriched + dedup_children
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding='utf-8')

    agg_count = sum(1 for r in enriched if r.get('is_aggregator') == 'yes')
    scraped = sum(1 for r in enriched if r.get('formal_extraction_status') == 'scraped')
    report = {
        'generated_at': now_iso(),
        'input_records': len(records),
        'enriched_records': len(enriched),
        'aggregator_records': agg_count,
        'scraped_records': scraped,
        'fetch_failed_records': len(enriched) - scraped,
        'child_links_added': len(dedup_children),
        'combined_output_records': len(combined),
        'with_address': sum(1 for r in combined if r.get('address')),
        'with_contact': sum(1 for r in combined if r.get('contact')),
        'with_price': sum(1 for r in combined if r.get('price_text')),
        'with_capacity': sum(1 for r in combined if r.get('capacity_text')),
        'missing_fields_distribution': dict(Counter(r.get('missing_formal_fields') or 'none' for r in enriched).most_common(20)),
        'aggregator_domains': dict(Counter(r.get('aggregator_domain') for r in enriched if r.get('is_aggregator') == 'yes').most_common(30)),
        'duration_seconds': round(time.time() - started, 1),
        'output': str(out),
    }
    rep = Path(args.report) if args.report else out.with_suffix('.report.json')
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
