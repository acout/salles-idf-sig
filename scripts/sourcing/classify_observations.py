#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from common import ROOT, now_iso


# ── Aggregator / listing / directory domains ──────────────────────────────────
AGGREGATOR_DOMAINS = {
    'abcsalles.com','1001salles.com','privateaser.com','pagesjaunes.fr',
    'yelp.com','m.yelp.com','spectable.com','kactus.com','directsalles.com',
    'snapevent.fr','jemepropose.com','evenementielpourtous.com','funbooker.com',
    'peerspace.com','eventlocations.com','eventplanner.net','native-spaces.com',
    'bcoworker.com','workin.space','chateauform.com','lesite.izyshow.com',
    'justacote.com','lofficieldessalles.com','salle.org','location-salle.com',
    'louerunesalle.com','villedata.com','combien-coute.fr','annuaire-mairie.fr',
    'sallesdesfetes.fr','locationsalle.fr','salledesfete.fr',
}

SOCIAL_DOMAINS = {'facebook.com','m.facebook.com','instagram.com','youtube.com','tiktok.com'}

# ── URL patterns that signal aggregator/listing/search pages ──────────────────
AGGREGATOR_URL_PATTERNS = [
    r'/search\?', r'/recherche\?', r'/lieux\b', r'/venues\b',
    r'/location-de-salle\b', r'/salle-a-louer\b',
    r'/find\?', r'/explore\b', r'/category\b',
]

# ── Municipal / institutional patterns in domain or URL ───────────────────────
MUNICIPAL_PATTERNS = [
    'ville-','mairie','mjc','centre-social','maison-des','ccas','.gouv.fr',
    'maisonquartier','mediatheque','bibliotheque',
]

# ── IDF communes we care about (banlieue sud focus) ──────────────────────────
IDF_COMMUNES = [
    'cachan','chatillon','châtillon','montrouge','bagneux','arcueil',
    'malakoff','bourg-la-reine','gentilly','villejuif','clamart','vanves',
    'sceaux','fontenay-aux-roses','le-kremlin-bicetre','kremlin-bicetre',
    'ivry-sur-seine','vitry-sur-seine','choisy-le-roi','thiais','orly',
    'alfortville','saint-mandé','vincennes','montreuil','paris',
    'nanterre','courbevoie','puteaux','rueil-malmaison','colombes',
    'meudon','issy-les-moulineaux','boulogne-billancourt','asnières',
    'aubervilliers','saint-denis','pantin','bagnolet',
    'les-lilas','lilas','bouscat','gradignan','pessac','talence',
    'charenton','joinville','nogent-sur-marne','saint-maur',
    'champigny','bry-sur-marne','noisy-le-grand','rosny-sous-bois',
    'fontenay-sous-bois','maisons-alfort','creteil','bonneuil',
    'sucy-en-brie','orly','villeneuve-saint-georges','villeneuve-le-roi',
    'thiais','choisy-le-roi','rungis','chevilly-larue',
    'hay-les-roses','freneux','freneux-taverny',
]

IDF_DEPS = {'75', '92', '93', '94', '77', '78', '91', '95'}

# ── Known homonyms / out-of-zone that appear in IDF searches ──────────────────
HOMONYM_REJECT = {
    'chatillon-en-vendelais','chatillon-en-vendelais','vendelais',
    'bourg-la-reine-97','bourg la reunion',
    'arcueil-97','arcachon',
    'malakoff-97',
    'bagneux-97',
    'montrouge-97',
    'cachan-97',
    'sceaux-97',
}

OUT_OF_ZONE_KEYWORDS = [
    'texas','usa','united states','india','uk ','canada','spain','italy',
    'germany','mexico','brazil','australia','japan','china',
    'royan','loiret','vendelais','bretagne','rennes','nantes','bordeaux',
    'lyon','marseille','toulouse','lille','nice','strasbourg',
    'reims','orléans','dijon','angers','poitiers','limoges',
    'châtillon-en-vendelais','chatillon-en-vendelais',
    'châtillon-sur-seine','chatillon-sur-seine',
    'châtillon-en-michaille',
]


def normalize_domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        host = urlparse(str(url or '')).netloc.replace('www.','').lower()
        return host.split(':')[0]
    except Exception:
        return ''


def classify_page_type(obs: dict) -> tuple[str, str]:
    """Returns (page_type, source_reliability)."""
    domain = obs.get('source_domain', '') or normalize_domain(obs.get('source_url', ''))
    url = str(obs.get('source_url', '')).lower()
    title = str(obs.get('source_title', '')).lower()
    snippet = str(obs.get('source_snippet', '')).lower()
    combined = f'{domain} {url} {title} {snippet}'

    # Social
    if domain in SOCIAL_DOMAINS:
        return 'social', 'S1'

    # Aggregator domains
    if domain in AGGREGATOR_DOMAINS:
        return 'aggregator_listing', 'S1'

    # Aggregator URL patterns
    for pat in AGGREGATOR_URL_PATTERNS:
        if re.search(pat, url):
            return 'aggregator_listing', 'S1'

    # Google / Maps / Places (not yet used but ready)
    if domain in ('maps.google.com','google.com','google.fr') and '/maps' in url:
        return 'google_maps', 'S2'
    if domain in ('www.google.com','google.fr') and '/search' in url:
        return 'google_search', 'S1'

    # Municipal / institutional
    if any(pat in combined for pat in MUNICIPAL_PATTERNS):
        # Check if rental page
        if any(k in combined for k in ['location de salle','salle à louer','réserver une salle','réservation salle','louer une salle','privatisation','mise à disposition','location salle']):
            return 'official_rental_page', 'S4'
        return 'municipal_facility_page', 'S3'

    # OSM (not yet but ready)
    if 'openstreetmap.org' in domain:
        return 'osm_object', 'S3'

    # PDF
    if url.endswith('.pdf') or '/pdf/' in url:
        if any(k in combined for k in ['tarif','prix','location','salle','mairie','municipale']):
            return 'official_rental_page', 'S4'
        return 'pdf_document', 'S2'

    # Official .fr domains with rental signals
    if domain.endswith('.fr') or domain.endswith('.gouv.fr'):
        if any(k in combined for k in ['location de salle','salle à louer','réserver une salle','réservation','louer une salle','privatisation','mise à disposition','location salle','tarif','studio à louer']):
            return 'official_rental_page', 'S4'
        return 'official_venue_page', 'S3'

    # Studio / dojo / yoga / dance sites with rental signals
    rental_signals = ['location de salle','location salle','louer','privatisation','mise à disposition',
                      'salle à louer','studio à louer','location studio','réservation',
                      'tarif','prix','à la location']
    venue_studio_patterns = ['dojo','yoga','danse','studio','pilates','martial','salle',
                              'arts martiaux','boxe','crossfit','mouvement','wellness']
    has_rental = any(k in combined for k in rental_signals)
    has_venue = any(k in combined for k in venue_studio_patterns)

    if has_rental and has_venue:
        return 'official_rental_page', 'S4'
    if has_rental:
        return 'official_rental_page', 'S3'
    if has_venue and not any(k in combined for k in ['cours uniquement','abonnement','fitness park','salle de sport','club de sport']):
        return 'official_venue_page', 'S3'

    # Co-working / corporate
    if any(k in combined for k in ['coworking','bureau','office space','shared office','spaces']):
        return 'coworking_corporate', 'S2'

    # Course-only / gym / fitness
    if any(k in combined for k in ['fitness park','fitnesspark','salle de sport','club de sport','abonnement mensuel','cours uniquement','réserver un cours','cours collectif']):
        return 'course_only_page', 'S1'

    # Leboncoin / classifieds
    if 'leboncoin' in domain:
        return 'classified_listing', 'S1'

    # Remaining
    if domain.endswith('.fr') or domain.endswith('.com'):
        return 'unknown_website', 'S2'
    return 'unknown', 'S0'


def classify_geo(obs: dict) -> tuple[str, str]:
    """Returns (geo_status, geo_detail)."""
    city = str(obs.get('candidate_city_hint', '')).lower().strip()
    dept = str(obs.get('candidate_department_hint', '')).strip()
    url = str(obs.get('source_url', '')).lower()
    title = str(obs.get('source_title', '')).lower()
    snippet = str(obs.get('source_snippet', '')).lower()
    combined = f'{city} {dept} {url} {title} {snippet}'

    # Check homonyms
    for h in HOMONYM_REJECT:
        if h in combined:
            return 'homonym', h

    # Check out-of-zone
    for kw in OUT_OF_ZONE_KEYWORDS:
        if kw in combined:
            return 'out_of_zone', kw

    # Check IDF match
    for c in IDF_COMMUNES:
        if c in combined:
            return 'in_scope', c

    if dept in IDF_DEPS:
        return 'in_scope', f'dept_{dept}'

    # Unknown — could not determine from hints alone
    return 'geo_unknown', ''


SOURCE_RELIABILITY_WEIGHT = {
    'S5': 5, 'S4': 4, 'S3': 3, 'S2': 2, 'S1': 1, 'S0': 0,
}


def classify_run(input_path: Path, output_path: Path, report_path: Path) -> dict:
    obs_list = json.loads(input_path.read_text(encoding='utf-8'))
    classified = []
    page_type_counts = Counter()
    reliability_counts = Counter()
    geo_status_counts = Counter()
    page_type_by_provider = Counter()
    geo_detail_examples = {'homonym': [], 'out_of_zone': [], 'geo_unknown': []}

    for obs in obs_list:
        page_type, reliability = classify_page_type(obs)
        geo_status, geo_detail = classify_geo(obs)
        obs['page_type'] = page_type
        obs['source_reliability'] = reliability
        obs['geo_status'] = geo_status
        obs['geo_detail'] = geo_detail
        classified.append(obs)
        page_type_counts[page_type] += 1
        reliability_counts[reliability] += 1
        geo_status_counts[geo_status] += 1
        page_type_by_provider[f'{obs["provider"]}:{page_type}'] += 1
        if geo_status in geo_detail_examples and len(geo_detail_examples[geo_status]) < 10:
            geo_detail_examples[geo_status].append(f'{page_type} | {obs.get("source_domain","")} | {obs.get("source_title","")[:60]}')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(classified, ensure_ascii=False, indent=2), encoding='utf-8')

    in_scope_obs = [o for o in classified if o['geo_status'] == 'in_scope']
    high_quality_obs = [o for o in in_scope_obs if o['source_reliability'] in ('S3','S4','S5')]

    classified_high_path = output_path.parent / 'observations_classified_high_quality.json'
    classified_high_path.write_text(json.dumps(high_quality_obs, ensure_ascii=False, indent=2), encoding='utf-8')

    report = {
        'generated_at': now_iso(),
        'input_observations': len(obs_list),
        'output_observations': len(classified),
        'page_type_distribution': dict(page_type_counts.most_common()),
        'source_reliability_distribution': dict(reliability_counts.most_common()),
        'geo_status_distribution': dict(geo_status_counts.most_common()),
        'page_type_by_provider_top20': dict(page_type_by_provider.most_common(20)),
        'in_scope_count': len(in_scope_obs),
        'in_scope_high_quality_count': len(high_quality_obs),
        'geo_detail_examples': geo_detail_examples,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description='Classify source observations by page_type, source_reliability, and geo_status.')
    ap.add_argument('--input', required=True, help='Path to observations.json from a discovery run')
    ap.add_argument('--output', required=True, help='Path to write classified observations.json')
    ap.add_argument('--report', required=True, help='Path to write classification report.json')
    args = ap.parse_args()
    report = classify_run(Path(args.input), Path(args.output), Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()