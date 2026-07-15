#!/usr/bin/env python3
"""Systemic venue page validator for the smart sourcing funnel.

Rules derived from analysis of 379 curated entities:
- 165 marked is_actual_venue=true by AI, but 61 are false positives (37%)
- 0 false negatives in is_actual_venue=false

Core insight: The AI cannot reliably distinguish "a page ABOUT venues" from
"a page FOR a specific venue" when working from short content snippets.

This validator applies deterministic rules BEFORE the AI classification.
If the validator says NOT a venue, the AI answer is overridden.
If the validator says probable_venue, the AI answer is kept.

Rules:
R1. PDF documents → never a venue (deliberation, listing, info booklet)
R2. Planning/schedule pages → never a venue
R3. Procedure/how-to pages → never a venue
R4. is_multi_venue_listing=true → directory, not a single venue
R5. Directory title patterns → not a specific venue
R6. Generic location titles → not a specific venue
R7. Too short/unclear names → reject (needs human review)
R8. Event pages → not a venue (festival, salon, congrès)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Deterministic validation rules ──────────────────────

LISTING_PATTERNS = [
    r'\bmeilleur\b', r'\btop\s', r'\bles\s', r'\bliste\b',
    r'\bannuaire\b', r'\brépertoire\b', r'\btrouver\b',
    r'\bou louer\b', r'\bcomment louer\b', r'\boù louer\b',
]

# URL paths that are NEVER venue pages (agenda, events, blog, etc.)
NON_VENUE_URL_PATHS = [
    '/agenda', '/planning', '/programme', '/programation',
    '/evenement', '/evenements', '/events', '/event',
    '/calendrier', '/schedule', '/spectacle', '/spectacles',
    '/representation', '/representations', '/billeterie', '/ticket',
    '/blog', '/article', '/articles', '/news',
    '/actualite', '/actualites', '/a-propos', '/about',
    '/contact', '/equipe', '/team', '/tarif', '/tarifs',
    '/prix', '/prices',
]

GENERIC_LOCATION_STARTS = [
    'location de ', 'locations de ', 'location de salle',
    'location de studio', 'location de salle de', 'location salles',
    'louer une salle', 'louer un studio', 'salle de réunion',
    'salle de séminaire', 'salles de réunion',
]
EVENT_PATTERNS = [
    r'\bévénement\b', r'\bevenement\b', r'\bfestival\b', r'\bforum\s',
    r'\bsalon\s', r'\bcongrès\b', r'\bcolloque\b', r'\bséminaire\b',
]


def validate_venue_page(item: dict, extraction: dict | None = None) -> tuple[bool, str, str]:
    """Validate whether an entity represents a real venue page.
    
    Returns: (is_valid_venue, rejection_reason, suggested_page_type)
    """
    ext = extraction or {}
    name = (item.get('canonical_name', '') or '').strip()
    url = (item.get('official_website_url', '') or item.get('primary_source_url', '') or '').strip()
    name_lower = name.lower()
    url_lower = url.lower()

    # R1. PDF documents are NEVER venues
    if '[pdf]' in name_lower or name_lower.endswith('.pdf') or '/pdf' in url_lower:
        if 'délibération' in name_lower or 'deliberation' in name_lower:
            return False, 'pdf_document', 'pdf_deliberation'
        if 'studio' in name_lower and ('location' in name_lower or 'louer' in name_lower):
            return False, 'pdf_document', 'pdf_listing'
        return False, 'pdf_document', 'pdf_other'

    # R1b. URL paths that are NOT venue pages (agenda, events, blog, contact, etc.)
    from urllib.parse import urlparse as _urlparse
    if url:
        path = _urlparse(url).path.lower().rstrip('/')
        for nvp in NON_VENUE_URL_PATHS:
            if path == nvp or path.endswith(nvp):
                return False, 'non_venue_url_path', f'url_path_{nvp.strip("/")}'

    # R2. Planning/schedule pages
    if name_lower.startswith('planning') or name_lower.startswith('programme') or 'emploi du temps' in name_lower:
        return False, 'planning_schedule', 'planning_document'

    # R3. Procedure/how-to pages
    if name_lower.startswith('procédure') or name_lower.startswith('comment ') or 'guide complet' in name_lower:
        return False, 'procedure_form', 'procedure_page'

    # R4. Multi-venue listings (from AI extraction)
    is_multi = str(ext.get('is_multi_venue_listing', {}).get('value', '')).lower()
    is_agg = str(ext.get('is_aggregator_listing', {}).get('value', '')).lower()
    if is_multi in ('true', 'yes') and is_agg in ('true', 'yes'):
        return False, 'directory_listing', 'multi_venue_listing'

    # R5. Directory title patterns
    for pattern in LISTING_PATTERNS:
        if re.search(pattern, name_lower):
            return False, 'directory_listing', 'directory_title'

    # R6. Generic location page titles
    # "Location de salle - 78180 Studio de danse" = generic (dash followed by code)
    # "Location de studio - Paris Marais Dance School" = specific (venue name after dash)
    for prefix in GENERIC_LOCATION_STARTS:
        if name_lower.startswith(prefix):
            if ' - ' in name:
                after_dash = name.split(' - ', 1)[1].strip()
                # If after dash is a postal code or < 15 chars, likely generic
                if len(after_dash) < 15 or re.match(r'^\d{5}', after_dash):
                    return False, 'generic_page', 'generic_location_page'
            else:
                # No dash = likely a generic page title
                return False, 'generic_page', 'generic_location_title'

    # R7. Too short / uninformative names
    if len(name) < 5:
        return False, 'unclear_name', 'name_too_short'

    # R8. Event pages
    for pattern in EVENT_PATTERNS:
        if re.search(pattern, name_lower):
            return False, 'event_page', 'event_not_venue'

    # Additional: aggregator listing from AI (even if is_actual_venue=true)
    if is_agg in ('true', 'yes'):
        return False, 'directory_listing', 'aggregator_listing'

    return True, 'looks_like_venue', 'probable_venue'


def validate_and_reclassify(run_dir: Path, output_path: Path | None = None):
    """Re-read curated + extraction and produce validated results."""
    curated = json.loads((run_dir / 'venue_entities_curated.json').read_text(encoding='utf-8'))
    
    # Load extraction results
    ext_dir = run_dir / 'ai_extraction'
    extraction_by_id = {}
    for batch_file in sorted(ext_dir.glob('results_batch_*.json')):
        batch = json.loads(batch_file.read_text(encoding='utf-8'))
        for r in batch:
            extraction_by_id[r['venue_entity_id']] = r.get('extraction', {})
    
    merged_file = ext_dir / 'results_merged_partial.json'
    if merged_file.exists() and not extraction_by_id:
        merged = json.loads(merged_file.read_text(encoding='utf-8'))
        for r in merged:
            extraction_by_id[r['venue_entity_id']] = r.get('extraction', {})

    stats = Counter()
    validated_entities = []
    rejected_entities = []
    
    for entity in curated:
        eid = entity['venue_entity_id']
        ext = extraction_by_id.get(eid, {})
        
        is_valid, reason, page_type = validate_venue_page(entity, ext)
        stats[reason] += 1
        
        entity['validation_is_valid_venue'] = is_valid
        entity['validation_reason'] = reason
        entity['validation_page_type'] = page_type
        
        if is_valid:
            validated_entities.append(entity)
        else:
            rejected_entities.append(entity)

    print(f'Curated entities: {len(curated)}')
    print(f'Validated as real venues: {len(validated_entities)}')
    print(f'Rejected (not actual venues): {len(rejected_entities)}')
    for reason, count in stats.most_common():
        print(f'  {reason}: {count}')
    
    # Save results
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            'total_curated': len(curated),
            'validated_venues': len(validated_entities),
            'rejected': len(rejected_entities),
            'validation_stats': dict(stats),
            'validated_entities': validated_entities,
            'rejected_entities': rejected_entities,
        }, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'\nSaved to {output_path}')

    return validated_entities, rejected_entities, stats


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', default='data/discovery_runs/20260620_multisource_lineage_enriched')
    ap.add_argument('--output', default='data/discovery_runs/20260620_multisource_lineage_enriched/validated_venues.json')
    args = ap.parse_args()
    
    run_dir = Path(args.run_dir)
    output = Path(args.output) if args.output else None
    validate_and_reclassify(run_dir, output)