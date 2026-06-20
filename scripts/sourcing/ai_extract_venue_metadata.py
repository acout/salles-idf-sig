#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter

SCHEMA_VERSION = '2026-06-20.v1'

EXTRACTION_PROMPT = """You are a venue metadata extraction assistant. Given the page content of a venue listing page, extract structured venue information.

IMPORTANT RULES:
1. Only extract information that is EXPLICITLY stated in the content. Do NOT infer or hallucinate.
2. For each field, provide:
   - value: the extracted value (null if not found)
   - evidence_quote: the EXACT text from the content that supports this value (empty string if not found)
   - confidence: 0.0-1.0 (how confident you are that this value is correct and belongs to THIS specific venue, not another venue on the same page)
3. If the page is an aggregator listing multiple venues, note that and set is_multi_venue_listing to true.
4. If this is a course/gym/fitness page that does NOT appear to rent space to third parties, set rental_possible to "no".
5. All prices should be in euros. Parse "35€/h" as hourly_eur=35, "180€/jour" as daily_eur=180.
6. Capacity: distinguish between "seated" (assis), "standing" (debout), "movement" (mouvement/danse/yoga), and "surface_m2" if given.
7. This is for FRANCE, Île-de-France region. Text is in French.

OUTPUT FORMAT (JSON only, no markdown, no explanation):
{
  "venue_name": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "is_aggregator_listing": {"value": false, "evidence_quote": "...", "confidence": 0.0},
  "is_multi_venue_listing": {"value": false, "evidence_quote": "...", "confidence": 0.0},
  "is_actual_venue": {"value": true, "evidence_quote": "...", "confidence": 0.0},
  "rental_possible": {"value": "yes|no|unclear", "evidence_quote": "...", "confidence": 0.0},
  "address": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "city": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "postal_code": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "phone": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "email": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "website": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "specific_rental_page": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "price": {
    "value": {"hourly_eur": null, "half_day_eur": null, "daily_eur": null, "raw": "..."},
    "evidence_quote": "...",
    "confidence": 0.0
  },
  "capacity": {
    "value": {"seated": null, "standing": null, "movement": null, "surface_m2": null, "raw": "..."},
    "evidence_quote": "...",
    "confidence": 0.0
  },
  "rental_restrictions": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "venue_type": {"value": "...", "evidence_quote": "...", "confidence": 0.0},
  "activity_tags": {"value": ["..."], "evidence_quote": "...", "confidence": 0.0},
  "pros": {"value": ["..."], "evidence_quote": "...", "confidence": 0.0},
  "cons": {"value": ["..."], "evidence_quote": "...", "confidence": 0.0},
  "missing_fields": ["..."]
}

Activity tags should be from: danse, yoga, pilates, arts_martiaux, dojo, theatre, musique, coworking, conference, seminaire, evenement, atelier, bien_etre, fitness, escalade, cirque, photo, tapis_rouge, autre

missing_fields should list important fields you could NOT find in the content (e.g., "price", "capacity", "contact_email", etc.)

PAGE CONTENT:
"""


def extract_entity_id_from_obs_id(obs_id: str) -> str:
    """Try to find the entity that contains this observation."""
    return obs_id


def main() -> None:
    ap = argparse.ArgumentParser(description='Generate LLM extraction prompts for curated venue entities.')
    ap.add_argument('--entities', required=True, help='Path to venue_entities_curated.json')
    ap.add_argument('--observations', required=True, help='Path to observations_classified.json')
    ap.add_argument('--cache-dir', required=True, help='Path to content_cache directory')
    ap.add_argument('--output-dir', required=True, help='Directory to write extraction prompts')
    ap.add_argument('--batch-size', type=int, default=1, help='Entities per prompt file')
    ap.add_argument('--limit', type=int, default=0, help='Max entities to process (0=all)')
    args = ap.parse_args()

    entities = json.loads(Path(args.entities).read_text(encoding='utf-8'))
    observations = json.loads(Path(args.observations).read_text(encoding='utf-8'))
    obs_by_id = {o['observation_id']: o for o in observations}
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.limit > 0:
        entities = entities[:args.limit]

    prompts = []
    no_content = []
    for i, entity in enumerate(entities):
        pid = entity.get('primary_observation_id', '')
        obs = obs_by_id.get(pid, {})
        content_path = obs.get('content_path', '')
        content = ''
        if content_path:
            cp = Path(content_path) if Path(content_path).is_absolute() else cache_dir.parent / content_path
            if cp.exists():
                content = cp.read_text(encoding='utf-8', errors='replace')[:8000]
        if not content:
            # Try finding by obs_id pattern
            for cp in sorted(cache_dir.glob(f'{pid}_*.txt')):
                content = cp.read_text(encoding='utf-8', errors='replace')[:8000]
                break
        if not content:
            no_content.append(entity.get('canonical_name', entity.get('venue_entity_id', '')))
            continue

        prompt_text = EXTRACTION_PROMPT + content[:8000] + '\n\nEXTRACT JSON:\n'

        prompt_entry = {
            'entity_index': i,
            'venue_entity_id': entity['venue_entity_id'],
            'canonical_name': entity.get('canonical_name', ''),
            'canonical_city': entity.get('canonical_city', ''),
            'official_website_url': entity.get('official_website_url', ''),
            'specific_rental_page_url': entity.get('specific_rental_page_url', ''),
            'primary_source_reliability': entity.get('primary_source_reliability', ''),
            'primary_page_type': entity.get('primary_page_type', ''),
            'observation_id': pid,
            'content_source': str(content_path) if content_path else 'cache_lookup',
            'prompt': prompt_text,
        }
        prompts.append(prompt_entry)

    # Write prompts
    output_file = output_dir / 'extraction_prompts.json'
    output_file.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding='utf-8')

    report = {
        'total_entities': len(entities),
        'prompts_generated': len(prompts),
        'no_content': len(no_content),
        'no_content_samples': no_content[:20],
        'output_file': str(output_file),
        'avg_prompt_chars': sum(len(p['prompt']) for p in prompts) // max(len(prompts), 1),
    }
    report_file = output_dir / 'extraction_prompt_report.json'
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()