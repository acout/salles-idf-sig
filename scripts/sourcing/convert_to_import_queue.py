#!/usr/bin/env python3
"""Convert curated venue entities + AI extraction into import_queue GeoJSON for the app.

Reads:
  - venue_entities_curated.json (entities with lineage)
  - AI extraction results (structured metadata per entity)
  - observations_classified.json (for coordinates and legacy fields)
  - field_evidence.json (for evidence lineage)

Writes:
  - public/import_queue.geojson (the app's data source)
  - data/import_queue/import_queue_<date>.csv (flat export)

Does NOT touch:
  - data/salles_all_idf.csv
  - data/salles_small_idf.csv
  - public/salles_small_idf.geojson
  - public/salles_all_idf.geojson
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent


def norm_text(s):
    return re.sub(r'\s+', ' ', str(s or '').strip())


def extract_price_text(price_val):
    """Convert structured price value to readable price_text."""
    if not price_val or price_val in (None, 'null', '{}'):
        return ''
    if isinstance(price_val, str):
        return price_val
    if isinstance(price_val, dict):
        parts = []
        if price_val.get('hourly_eur'):
            parts.append(f"{price_val['hourly_eur']}€/h")
        if price_val.get('half_day_eur'):
            parts.append(f"{price_val['half_day_eur']}€/demi-journée")
        if price_val.get('daily_eur'):
            parts.append(f"{price_val['daily_eur']}€/jour")
        raw = price_val.get('raw', '')
        return ' — '.join(parts) if parts else raw
    return ''


def extract_capacity_text(cap_val):
    """Convert structured capacity value to readable capacity_text."""
    if not cap_val or cap_val in (None, 'null', '{}'):
        return ''
    if isinstance(cap_val, str):
        return cap_val
    if isinstance(cap_val, dict):
        parts = []
        if cap_val.get('seated'):
            parts.append(f"{cap_val['seated']} assis")
        if cap_val.get('standing'):
            parts.append(f"{cap_val['standing']} debout")
        if cap_val.get('movement'):
            parts.append(f"{cap_val['movement']} mvt")
        if cap_val.get('surface_m2'):
            parts.append(f"{cap_val['surface_m2']}m²")
        raw = cap_val.get('raw', '')
        return ', '.join(parts) if parts else raw
    return ''


def build_import_queue(run_dir: Path, output_geojson: Path, output_csv_dir: Path, date_tag: str):
    curated = json.loads((run_dir / 'venue_entities_curated.json').read_text(encoding='utf-8'))
    observations = json.loads((run_dir / 'observations_classified.json').read_text(encoding='utf-8'))
    obs_by_id = {o['observation_id']: o for o in observations}

    # Load extraction results
    ext_dir = run_dir / 'ai_extraction'
    extraction_by_id = {}
    for batch_file in sorted(ext_dir.glob('results_batch_*.json')):
        batch = json.loads(batch_file.read_text(encoding='utf-8'))
        for r in batch:
            eid = r.get('venue_entity_id', '')
            extraction_by_id[eid] = r.get('extraction', {})

    # Also try merged results
    merged_file = ext_dir / 'results_merged_partial.json'
    if merged_file.exists() and not extraction_by_id:
        merged = json.loads(merged_file.read_text(encoding='utf-8'))
        for r in merged:
            eid = r.get('venue_entity_id', '')
            extraction_by_id[eid] = r.get('extraction', {})

    # Convert to GeoJSON features
    features = []
    for entity in curated:
        eid = entity['venue_entity_id']
        ext = extraction_by_id.get(eid, {})
        if not isinstance(ext, dict):
            ext = {}

        # Get coordinates from primary observation
        pid = entity.get('primary_observation_id', '')
        obs = obs_by_id.get(pid, {})
        lat = obs.get('candidate_lat_hint') or entity.get('canonical_lat')
        lon = obs.get('candidate_lon_hint') or entity.get('canonical_lon')

        # Helper to get extraction value
        def ext_val(field, default=''):
            v = ext.get(field, {})
            if isinstance(v, dict):
                return v.get('value', default)
            return v if v else default

        def ext_quote(field):
            v = ext.get(field, {})
            if isinstance(v, dict):
                return v.get('evidence_quote', '')
            return ''

        def ext_conf(field):
            v = ext.get(field, {})
            if isinstance(v, dict):
                try:
                    return float(v.get('confidence', 0))
                except (ValueError, TypeError):
                    return 0.0
            return 0.0

        # Rental status mapping
        rental_raw = str(ext_val('rental_possible', '')).lower()
        if rental_raw == 'yes':
            rental_status = 'possible'
        elif rental_raw == 'no':
            rental_status = 'unlikely'
        else:
            rental_status = 'unclear'

        # Is actual venue
        is_actual = ext_val('is_actual_venue', '')
        is_agg = ext_val('is_aggregator_listing', '')

        # Page type from entity classification
        page_type = entity.get('primary_page_type', 'unknown')
        reliability = entity.get('primary_source_reliability', 'S0')
        geo_status = entity.get('geo_status', 'unknown')

        # Price
        price_val = ext.get('price', {})
        price_text = extract_price_text(price_val.get('value', '') if isinstance(price_val, dict) else price_val)

        # Capacity
        cap_val = ext.get('capacity', {})
        capacity_text = extract_capacity_text(cap_val.get('value', '') if isinstance(cap_val, dict) else cap_val)
        cap_max = 0
        if isinstance(cap_val, dict) and isinstance(cap_val.get('value'), dict):
            cap_max = max(
                cap_val['value'].get('seated', 0) or 0,
                cap_val['value'].get('standing', 0) or 0,
                cap_val['value'].get('movement', 0) or 0,
            )

        # Address
        address = ext_val('address', '') or obs.get('candidate_address_hint', '') or entity.get('canonical_city', '')
        city = ext_val('city', '') or entity.get('canonical_city', '') or obs.get('candidate_city_hint', '')
        department = entity.get('canonical_department', '') or obs.get('candidate_department_hint', '')

        # Contact
        phone = ext_val('phone', '')
        email = ext_val('email', '')
        contact_parts = [p for p in [phone, email] if p and str(p) not in ('null', 'None', '')]
        contact = ' — '.join(contact_parts) if contact_parts else ''

        # Website
        website = entity.get('official_website_url', '') or ext_val('website', '')
        rental_page = entity.get('specific_rental_page_url', '') or ext_val('specific_rental_page', '')

        # Venue name
        name = ext_val('venue_name', '') or entity.get('canonical_name', '') or obs.get('source_title', '')
        # Clean aggregator-style names
        if name and len(name) > 80:
            name = name[:77] + '...'

        # Category / venue type
        venue_type = ext_val('venue_type', '')
        if isinstance(venue_type, list):
            venue_type = ', '.join(str(v) for v in venue_type if v)

        # Activity tags
        activity_tags = ext_val('activity_tags', '')
        if isinstance(activity_tags, list):
            activity_tags = ', '.join(str(v) for v in activity_tags if v)

        # Source URL
        source_url = entity.get('primary_source_url', '') or obs.get('source_url', '')
        source_domain = entity.get('primary_source_domain', '') or obs.get('source_domain', '')

        # Evidence text (key quotes)
        evidence_parts = []
        for field in ['rental_possible', 'price', 'capacity', 'address']:
            q = ext_quote(field)
            if q and str(q) not in ('null', ''):
                evidence_parts.append(f'{field}: {str(q)[:100]}')
        evidence_text = ' | '.join(evidence_parts)

        # Missing important fields
        missing = ext.get('missing_fields', [])
        if isinstance(missing, list):
            missing_str = ', '.join(str(m) for m in missing)
        else:
            missing_str = str(missing)

        # Observation count
        obs_count = entity.get('observation_count', 1)

        # Build feature
        # Skip entities that are clearly not venues
        is_venue_val = ext_val('is_actual_venue', '')
        if str(is_venue_val).lower() in ('false', 'no') and str(is_agg).lower() in ('true', 'yes'):
            continue  # Skip aggregator listings that aren't actual venues

        # Confidence score
        conf_fields = ['rental_possible', 'price', 'capacity', 'address', 'phone', 'email']
        conf_sum = sum(ext_conf(f) for f in conf_fields)
        conf_count = sum(1 for f in conf_fields if ext_conf(f) > 0)
        overall_confidence = conf_sum / max(conf_count, 1)

        # Fit beyond score (heuristic)
        fit_score = 50  # base
        if rental_status == 'possible':
            fit_score += 20
        elif rental_status == 'unlikely':
            fit_score -= 30
        if reliability in ('S4', 'S5'):
            fit_score += 10
        elif reliability == 'S3':
            fit_score += 5
        elif reliability in ('S1', 'S0'):
            fit_score -= 10
        if page_type == 'official_rental_page':
            fit_score += 10
        elif page_type == 'aggregator_listing':
            fit_score -= 5
        if contact:
            fit_score += 5
        if price_text:
            fit_score += 5
        if capacity_text:
            fit_score += 5
        fit_score = max(0, min(100, fit_score))

        # Formal completeness
        formal_fields = ['address', 'phone', 'email', 'price', 'capacity']
        filled = sum(1 for f in formal_fields if ext_val(f, '') and str(ext_val(f, '')) not in ('null', 'None', ''))
        formal_completeness = f"{filled}/{len(formal_fields)}"

        # Dataset tag
        is_candidate = page_type not in ('aggregator_listing', 'social', 'course_only_page')
        dataset = 'candidate' if is_candidate else 'aggregator'

        # Candidate status
        candidate_status = 'new'
        if rental_status == 'possible':
            candidate_status = 'to_contact'
        elif rental_status == 'unlikely':
            candidate_status = 'rejected'
        elif is_agg:
            candidate_status = 'aggregator'

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)] if lon and lat else [0, 0]
            } if lon and lat else None,
            "properties": {
                "candidate_id": eid,
                "name": norm_text(name),
                "city": norm_text(city),
                "department": department,
                "address": norm_text(address),
                "lat": float(lat) if lat else None,
                "lon": float(lon) if lon else None,
                "category": norm_text(venue_type),
                "capacity_text": norm_text(capacity_text),
                "capacity_max_detected": cap_max,
                "price_text": norm_text(price_text),
                "price_score": 0,
                "website": norm_text(website),
                "contact": norm_text(contact),
                "source_url": norm_text(source_url),
                "source_domain": norm_text(source_domain),
                "source_confidence": round(overall_confidence, 2),
                "fit_beyond_score": fit_score,
                "confidence_score": round(overall_confidence, 2),
                "actionability_score": fit_score,
                "formal_completeness_score": formal_completeness,
                "formal_extraction_status": "ai_extracted",
                "formal_scrape_checked_at": datetime.now().isoformat()[:10],
                "formal_scrape_content_type": page_type,
                "is_aggregator": "yes" if str(is_agg).lower() in ('true', 'yes') else "no",
                "aggregator_domain": source_domain if str(is_agg).lower() in ('true', 'yes') else "",
                "rental_possible_status": rental_status,
                "rental_possible_confidence": round(ext_conf('rental_possible'), 2),
                "rental_positive_signals": "",
                "rental_negative_signals": "",
                "rental_decision_needed": "yes" if rental_status == 'unclear' else "no",
                "rental_email_question": ext_quote('rental_possible')[:200] if rental_status == 'unclear' else "",
                "activity_tags": norm_text(activity_tags),
                "space_tags": "",
                "constraints_tags": norm_text(ext_val('rental_restrictions', '')),
                "description": "",
                "evidence_text": evidence_text,
                "missing_formal_fields": missing_str,
                "email_questions": "",
                "page_type": page_type,
                "source_reliability": reliability,
                "geo_status": geo_status,
                "specific_rental_page_url": norm_text(rental_page),
                "observation_count": obs_count,
                "candidate_status": candidate_status,
                "_dataset": dataset,
                "dedupe_key": f"{norm_text(name)}_{norm_text(city)}".lower().replace(' ', '_')[:80],
                "last_seen_at": datetime.now().isoformat()[:10],
            }
        }

        # Remove None geometry
        if feature['geometry'] is None:
            feature['geometry'] = {"type": "Point", "coordinates": [0, 0]}

        features.append(feature)

    # Build GeoJSON
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    # Write GeoJSON
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding='utf-8')

    # Write CSV
    import csv, io
    csv_path = output_csv_dir / f'import_queue_{date_tag}.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    all_keys = sorted(set(k for f in features for k in f['properties'].keys()))
    with io.StringIO() as buf:
        w = csv.DictWriter(buf, fieldnames=all_keys, extrasaction='ignore')
        w.writeheader()
        for f in features:
            row = {k: str(v) for k, v in f['properties'].items()}
            w.writerow(row)
        csv_path.write_text(buf.getvalue(), encoding='utf-8')

    # Report
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_features": len(features),
        "with_coords": sum(1 for f in features if f['geometry']['coordinates'] != [0, 0]),
        "without_coords": sum(1 for f in features if f['geometry']['coordinates'] == [0, 0]),
        "rental_possible": sum(1 for f in features if f['properties']['rental_possible_status'] == 'possible'),
        "rental_unclear": sum(1 for f in features if f['properties']['rental_possible_status'] == 'unclear'),
        "rental_unlikely": sum(1 for f in features if f['properties']['rental_possible_status'] == 'unlikely'),
        "page_type_distribution": dict(Counter(f['properties']['page_type'] for f in features).most_common()),
        "reliability_distribution": dict(Counter(f['properties']['source_reliability'] for f in features).most_common()),
        "dataset_distribution": dict(Counter(f['properties']['_dataset'] for f in features).most_common()),
        "has_price": sum(1 for f in features if f['properties']['price_text']),
        "has_capacity": sum(1 for f in features if f['properties']['capacity_text']),
        "has_address": sum(1 for f in features if f['properties']['address']),
        "has_contact": sum(1 for f in features if f['properties']['contact']),
        "has_rental_page": sum(1 for f in features if f['properties']['specific_rental_page_url']),
    }
    report_path = output_csv_dir / f'report_{date_tag}.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    return report


def main():
    ap = argparse.ArgumentParser(description='Convert curated entities + AI extraction to import queue GeoJSON for the app.')
    ap.add_argument('--run-dir', default='data/discovery_runs/20260620_multisource_lineage_enriched')
    ap.add_argument('--output', default='public/import_queue.geojson')
    ap.add_argument('--csv-dir', default='data/import_queue')
    ap.add_argument('--date-tag', default=datetime.now().strftime('%Y%m%d') + '_funnel_l4')
    args = ap.parse_args()

    report = build_import_queue(Path(args.run_dir), Path(args.output), Path(args.csv_dir), args.date_tag)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()