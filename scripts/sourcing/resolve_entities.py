#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from common import ROOT, now_iso


SCHEMA_VERSION = '2026-06-20.v1'

# ── Helpers ────────────────────────────────────────────────────────────────────

def norm_domain(url: str) -> str:
    try:
        return urlparse(str(url or '')).netloc.replace('www.','').lower().split(':')[0]
    except Exception:
        return ''


def norm_url(url: str) -> str:
    return str(url or '').split('#')[0].rstrip('/').lower()


def norm_name(name: str) -> str:
    s = str(name or '').lower().strip()
    s = re.sub(r'[àâä]', 'a', s)
    s = re.sub(r'[éèêë]', 'e', s)
    s = re.sub(r'[îï]', 'i', s)
    s = re.sub(r'[ôö]', 'o', s)
    s = re.sub(r'[ùûü]', 'u', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def name_similarity(a: str, b: str) -> float:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.75
    # Token overlap
    ta, tb = set(na.split()), set(nb.split())
    inter = ta & tb
    union = ta | tb
    if not union:
        return 0.0
    return len(inter) / len(union)


# ── Aggregator domains ────────────────────────────────────────────────────────

AGGREGATOR_DOMAINS = {
    'abcsalles.com','1001salles.com','privateaser.com','pagesjaunes.fr',
    'yelp.com','m.yelp.com','spectable.com','kactus.com','directsalles.com',
    'snapevent.fr','jemepropose.com','evenementielpourtous.com','funbooker.com',
    'peerspace.com','eventlocations.com','eventplanner.net','native-spaces.com',
    'bcoworker.com','workin.space','chateauform.com','lesite.izyshow.com',
    'justacote.com','lofficieldessalles.com','salle.org','location-salle.com',
    'louerunesalle.com','villedata.com','combien-coute.fr','annuaire-mairie.fr',
    'sallesdesfetes.fr','locationsalle.fr','salledesfete.fr',
    'yogmee.fr','easyzic.com',
}


# ── Merge key computation ─────────────────────────────────────────────────────

def compute_merge_key(obs: dict) -> str:
    """Compute a stable merge key for entity resolution."""
    domain = obs.get('source_domain', '') or norm_domain(obs.get('source_url', ''))
    name = obs.get('candidate_name_hint', '') or obs.get('source_title', '')
    city = str(obs.get('candidate_city_hint', '')).lower().strip()
    url = norm_url(obs.get('source_url', ''))

    # Aggregators: each aggregator URL is a separate "venue listing" observation
    # but they should NOT be merged across different aggregator pages
    if domain in AGGREGATOR_DOMAINS:
        # Use full URL as key for aggregators — each listing is a separate observation
        # that will later be linked to a canonical entity if it references the same venue
        return f'agg_{url}'

    # For official/municipal/venue sites: merge by normalized domain + name similarity
    # This means 2 observations from ville-cachan.fr about different pages
    # will be merged if they refer to the same venue name
    return f'venue_{domain}_{norm_name(name)}_{city}'


def resolve_primary_source(observations: list[dict]) -> dict:
    """Given a list of observations for the same entity, determine primary source info."""
    # Sort by source_reliability (S5 > S4 > S3 > S2 > S1 > S0), then by page_type priority
    rel_order = {'S5': 5, 'S4': 4, 'S3': 3, 'S2': 2, 'S1': 1, 'S0': 0}
    type_order = {'official_rental_page': 6, 'official_venue_page': 5, 'municipal_facility_page': 4,
                  'pdf_document': 3, 'coworking_corporate': 2, 'aggregator_listing': 1, 'social': 0}

    sorted_obs = sorted(observations, key=lambda o: (
        rel_order.get(o.get('source_reliability', 'S0'), 0),
        type_order.get(o.get('page_type', 'unknown'), 0),
    ), reverse=True)

    primary = sorted_obs[0] if sorted_obs else observations[0]

    # Gather all URLs and find best rental page vs general website
    rental_urls = set()
    website_urls = set()
    for o in observations:
        r = o.get('specific_rental_page_url', '')
        w = o.get('website_url', '') or o.get('source_url', '')
        if r:
            rental_urls.add(r)
        if w:
            website_urls.add(w)

    official_website = primary.get('website_url', '') or primary.get('source_url', '')
    specific_rental = ''
    # Prefer rental page from higher-reliability observations
    for o in sorted_obs:
        r = o.get('specific_rental_page_url', '')
        w = o.get('website_url', '') or o.get('source_url', '')
        if r and r != w and o.get('source_reliability') in ('S3', 'S4', 'S5'):
            specific_rental = r
            official_website = w
            break

    if not specific_rental and rental_urls:
        # Fallback: any rental URL that differs from website
        for ru in sorted(rental_urls):
            if ru != official_website:
                specific_rental = ru
                break

    return {
        'primary_observation_id': primary.get('observation_id', ''),
        'primary_source_url': primary.get('source_url', ''),
        'primary_source_domain': primary.get('source_domain', ''),
        'primary_source_reliability': primary.get('source_reliability', 'S0'),
        'primary_page_type': primary.get('page_type', 'unknown'),
        'official_website_url': official_website,
        'specific_rental_page_url': specific_rental,
        'best_name_hint': primary.get('candidate_name_hint', '') or primary.get('source_title', ''),
        'best_city_hint': primary.get('candidate_city_hint', ''),
        'best_address_hint': primary.get('candidate_address_hint', ''),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def build_entities(input_path: Path, output_path: Path, report_path: Path) -> dict:
    obs_list = json.loads(input_path.read_text(encoding='utf-8'))

    # Step 1: Group by merge key
    groups = defaultdict(list)
    for obs in obs_list:
        key = compute_merge_key(obs)
        groups[key].append(obs)

    # Step 2: For aggregator groups, keep each as a separate observation-entity
    # For non-aggregator groups, merge into canonical entities
    entities = []
    aggregator_obs_count = 0
    venue_entity_count = 0
    multi_obs_entities = 0

    for key, group_obs in groups.items():
        if key.startswith('agg_'):
            # Aggregator observations stay as individual observations
            # but linked to potential canonical entities later
            for obs in group_obs:
                aggregator_obs_count += 1
                entities.append({
                    'venue_entity_id': obs['observation_id'],
                    'schema_version': SCHEMA_VERSION,
                    'entity_status': 'aggregator_observation',
                    'canonical_name': obs.get('candidate_name_hint', '') or obs.get('source_title', ''),
                    'canonical_city': obs.get('candidate_city_hint', ''),
                    'canonical_department': obs.get('candidate_department_hint', ''),
                    'canonical_lat': obs.get('candidate_lat_hint'),
                    'canonical_lon': obs.get('candidate_lon_hint'),
                    'official_website_url': obs.get('website_url', ''),
                    'specific_rental_page_url': obs.get('specific_rental_page_url', ''),
                    'source_observations': [obs['observation_id']],
                    'observation_count': 1,
                    'primary_observation_id': obs['observation_id'],
                    'primary_source_reliability': obs.get('source_reliability', 'S1'),
                    'primary_page_type': obs.get('page_type', 'aggregator_listing'),
                    'geo_status': obs.get('geo_status', 'geo_unknown'),
                })
        else:
            # Non-aggregator: merge observations about the same venue
            primary_info = resolve_primary_source(group_obs)
            obs_ids = [o['observation_id'] for o in group_obs]
            if len(group_obs) > 1:
                multi_obs_entities += 1
            venue_entity_count += 1
            entities.append({
                'venue_entity_id': f'venue_{key}',
                'schema_version': SCHEMA_VERSION,
                'entity_status': 'candidate',
                'canonical_name': primary_info['best_name_hint'],
                'canonical_city': primary_info['best_city_hint'],
                'canonical_department': group_obs[0].get('candidate_department_hint', ''),
                'canonical_lat': group_obs[0].get('candidate_lat_hint'),
                'canonical_lon': group_obs[0].get('candidate_lon_hint'),
                'official_website_url': primary_info['official_website_url'],
                'specific_rental_page_url': primary_info['specific_rental_page_url'],
                'source_observations': obs_ids,
                'observation_count': len(group_obs),
                'primary_observation_id': primary_info['primary_observation_id'],
                'primary_source_reliability': primary_info['primary_source_reliability'],
                'primary_page_type': primary_info['primary_page_type'],
                'geo_status': group_obs[0].get('geo_status', 'geo_unknown'),
            })

    # Step 3: Filter to in_scope high-quality for the curated view
    curated_entities = [e for e in entities
                       if e.get('geo_status') == 'in_scope'
                       and e.get('primary_source_reliability') in ('S3', 'S4', 'S5')
                       and e.get('primary_page_type') not in ('aggregator_listing', 'social', 'course_only_page')]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(entities, ensure_ascii=False, indent=2), encoding='utf-8')

    curated_path = output_path.parent / 'venue_entities_curated.json'
    curated_path.write_text(json.dumps(curated_entities, ensure_ascii=False, indent=2), encoding='utf-8')

    report = {
        'generated_at': now_iso(),
        'input_observations': len(obs_list),
        'total_entities': len(entities),
        'venue_entities': venue_entity_count,
        'aggregator_observations': aggregator_obs_count,
        'multi_obs_entities': multi_obs_entities,
        'curated_in_scope_high_quality': len(curated_entities),
        'curated_by_page_type': dict(Counter(e.get('primary_page_type','') for e in curated_entities).most_common()),
        'curated_by_reliability': dict(Counter(e.get('primary_source_reliability','') for e in curated_entities).most_common()),
        'entities_with_rental_page': sum(1 for e in entities if e.get('specific_rental_page_url')),
        'entities_with_website': sum(1 for e in entities if e.get('official_website_url')),
        'entities_with_both_distinct': sum(1 for e in entities if e.get('specific_rental_page_url') and e.get('official_website_url') and e['specific_rental_page_url'] != e['official_website_url']),
        'geo_status_distribution': dict(Counter(e.get('geo_status','') for e in entities).most_common()),
        'entity_status_distribution': dict(Counter(e.get('entity_status','') for e in entities).most_common()),
        'outputs': {
            'all_entities': str(output_path),
            'curated_entities': str(curated_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description='Resolve source observations into canonical venue entities.')
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--report', required=True)
    args = ap.parse_args()
    report = build_entities(Path(args.input), Path(args.output), Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()