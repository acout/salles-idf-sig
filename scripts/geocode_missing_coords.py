#!/usr/bin/env python3
"""
Geocode features missing coordinates in import_queue.geojson.

Uses two geocoding services in priority order:
1. BAN (api-adresse.data.gouv.fr) — best for French street addresses
2. Nominatim (openstreetmap.org) — best for venue name + city searches

Reads import_queue.geojson, finds features with coordinates [0,0],
geocodes them, updates geometry.coordinates and properties.lat/lon,
and marks failures with "geocode_failed" in missing_formal_fields.

Usage:
    python3 scripts/geocode_missing_coords.py [--input INPUT] [--output OUTPUT] [--dry-run]
    
    Default: reads and writes  public/import_queue.geojson in-place.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_INPUT = PROJECT_DIR / "public" / "import_queue.geojson"

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

BAN_USER_AGENT = "salles-idf-sig geocoder (BAN) / 1.0"
NOMINATIM_USER_AGENT = "salles-idf-sig geocoder (Nominatim) / 1.0"

IDF_BBOX = (48.1, 49.1, 1.4, 3.6)  # minLat, maxLat, minLon, maxLon


def inside_idf(lat: float, lon: float) -> bool:
    """Check if coordinates are within Île-de-France bounding box."""
    min_lat, max_lat, min_lon, max_lon = IDF_BBOX
    return min_lat <= lat <= max_lat and min_lon <= lon


# ---------------------------------------------------------------------------
# Geocoding functions
# ---------------------------------------------------------------------------

def geocode_ban(query: str) -> dict | None:
    """Geocode using BAN (Base Adresse Nationale). Returns dict with lat, lon, label, score or None."""
    params = urllib.parse.urlencode({"q": query, "limit": 1, "type": "housenumber"})
    url = f"{BAN_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": BAN_USER_AGENT, "Accept": "application/json"})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            features = data.get("features", [])
            if features:
                f = features[0]
                coords = f.get("geometry", {}).get("coordinates", [None, None])
                lon_opt, lat_opt = (coords[0], coords[1]) if len(coords) >= 2 else (None, None)
                props = f.get("properties", {})
                if lat_opt is not None and lon_opt is not None:
                    return {
                        "lat": float(lat_opt),
                        "lon": float(lon_opt),
                        "label": props.get("label", ""),
                        "score": props.get("score"),
                        "source": "ban",
                    }
            return None  # No results
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 3 * (attempt + 1)
                print(f"    [BAN rate-limited] waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    [BAN HTTP {e.code}] attempt {attempt+1}: {e}", file=sys.stderr)
                time.sleep(1)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
            print(f"    [BAN error] attempt {attempt+1}: {e}", file=sys.stderr)
            time.sleep(1)
    return None


def geocode_nominatim(query: str) -> dict | None:
    """Geocode using Nominatim. Returns dict with lat, lon, label, source or None."""
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "fr",
    })
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": NOMINATIM_USER_AGENT,
        "Accept": "application/json",
    })

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data and len(data) > 0:
                item = data[0]
                lat_s = item.get("lat")
                lon_s = item.get("lon")
                if lat_s and lon_s:
                    lat, lon = float(lat_s), float(lon_s)
                    return {
                        "lat": lat,
                        "lon": lon,
                        "label": item.get("display_name", ""),
                        "score": None,
                        "source": "nominatim",
                    }
            return None  # No results
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 3 * (attempt + 1)
                print(f"    [Nominatim rate-limited] waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    [Nominatim HTTP {e.code}] attempt {attempt+1}: {e}", file=sys.stderr)
                time.sleep(2)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
            print(f"    [Nominatim error] attempt {attempt+1}: {e}", file=sys.stderr)
            time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

DEPT_NAMES = {
    "75": "Paris", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "91": "Essonne", "78": "Yvelines",
    "95": "Val-d'Oise", "77": "Seine-et-Marne",
}


def build_queries(props: dict) -> list[tuple[str, str]]:
    """
    Build geocoding queries from properties.
    Returns list of (query_string, strategy_name) tuples, in priority order.
    """
    name = (props.get("name") or "").strip()
    address = (props.get("address") or "").strip()
    city = (props.get("city") or "").strip()
    department = (props.get("department") or "").strip()
    postal_code = (props.get("postal_code") or "").strip()
    evidence_text = (props.get("evidence_text") or "").strip()

    # Clean up address: remove if it's just the city name
    if address and address.lower() == city.lower():
        address = ""

    dept_name = DEPT_NAMES.get(department, "")

    queries = []

    # Strategy A: BAN-friendly full address (best quality)
    if address and address != city:
        parts = [address]
        if postal_code:
            parts.append(postal_code)
        elif city and city.lower() not in address.lower():
            parts.append(city)
        queries.append((", ".join(parts), "address_full_ban"))

    # Strategy B: name + city (good for specific venues)
    if name and city:
        q = f"{name}, {city}"
        if postal_code:
            q += f" {postal_code}"
        queries.append((q, "name_city_nominatim"))

    # Strategy C: Try evidence_text address if it contains street info
    # Evidence text sometimes has format like "Salle X | 7, rue Saint-Éloi, Gentilly"
    if evidence_text and "|" in evidence_text:
        # Extract address part after pipe
        parts_pipe = evidence_text.split("|")
        if len(parts_pipe) >= 2:
            addr_part = parts_pipe[-1].strip()
            # Check if it looks like an address (has a number)
            if any(c.isdigit() for c in addr_part[:5]):
                q = addr_part
                if city:
                    q = f"{addr_part}, {city}"
                if postal_code:
                    q += f" {postal_code}"
                queries.append((q, "evidence_address_ban"))

    # Strategy D: name + department name (for venues without city)
    if name and not city and dept_name:
        queries.append((f"{name}, {dept_name}, France", "name_dept_nominatim"))

    # Strategy E: name only with region (last resort)
    if name and not city and not address:
        queries.append((f"{name}, Île-de-France, France", "name_region_nominatim"))

    # Also try just city for city-level accuracy (fallback)
    if city and not address and not name:
        q = city
        if postal_code:
            q += f" {postal_code}"
        queries.append((q, "city_only"))

    # Deduplicate preserving order
    seen = set()
    unique = []
    for q, strat in queries:
        if q.lower() not in seen:
            seen.add(q.lower())
            unique.append((q, strat))

    return unique


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Geocode missing coordinates in import_queue.geojson")
    ap.add_argument("--input", default=str(DEFAULT_INPUT), help="Input GeoJSON file (default: public/import_queue.geojson)")
    ap.add_argument("--output", default=None, help="Output file (default: overwrites --input)")
    ap.add_argument("--dry-run", action="store_true", help="Don't write output, just print summary")
    ap.add_argument("--limit", type=int, default=0, help="Max features to geocode (0=all)")
    args = ap.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    print(f"Loading {input_path}...")
    geojson = json.loads(input_path.read_text(encoding="utf-8"))

    features = geojson["features"]
    total = len(features)
    print(f"Total features: {total}")

    # Find features with [0, 0] coordinates
    missing_indices = []
    for i, feat in enumerate(features):
        coords = feat["geometry"]["coordinates"]
        if coords == [0, 0] or coords == [0.0, 0.0]:
            missing_indices.append(i)

    print(f"Features missing coordinates: {len(missing_indices)}")

    if not missing_indices:
        print("Nothing to geocode. Exiting.")
        return

    if args.limit > 0:
        missing_indices = missing_indices[:args.limit]
        print(f"(Limited to {args.limit} features)")

    success_count = 0
    fail_count = 0
    no_query_count = 0
    success_examples = []
    failed_examples = []

    for idx_num, idx in enumerate(missing_indices):
        feat = features[idx]
        props = feat["properties"]
        name = props.get("name", "???")
        city = props.get("city", "")
        dept = props.get("department", "")
        address = props.get("address", "")

        queries = build_queries(props)

        if not queries:
            existing_mff = props.get("missing_formal_fields", "")
            if "geocode_failed" not in existing_mff:
                new_mff = (existing_mff + ",geocode_failed").lstrip(",")
                props["missing_formal_fields"] = new_mff
            no_query_count += 1
            fail_count += 1
            if len(failed_examples) < 20:
                failed_examples.append(f"  ❌ {name} ({city or 'no city'}, dept={dept}) — no query possible")
            print(f"[{idx_num+1}/{len(missing_indices)}] SKIP (no query): {name}")
            continue

        found = False
        for qi, (query, strategy) in enumerate(queries):
            short_q = query[:70]
            use_ban = "ban" in strategy
            source_label = "BAN" if use_ban else "Nominatim"

            print(f"[{idx_num+1}/{len(missing_indices)}] {name} ({city or '–'}) → '{short_q}' [{strategy}/{source_label}]", end="")
            sys.stdout.flush()

            result = geocode_ban(query) if use_ban else geocode_nominatim(query)

            # Rate limiting
            time.sleep(1.1 if not use_ban else 0.15)  # BAN is more permissive

            if result:
                lat, lon = result["lat"], result["lon"]
                label = result.get("label", "")
                source = result["source"]

                # Validate coordinates are in IDF
                if not inside_idf(lat, lon):
                    print(f" → outside IDF ({lat:.4f}, {lon:.4f})")
                    continue

                feat["geometry"]["coordinates"] = [lon, lat]
                props["lat"] = lat
                props["lon"] = lon
                # Store geocode metadata
                props["geocode_source"] = source
                props["geocode_label"] = label[:200] if label else ""
                if result.get("score") is not None:
                    props["geocode_score"] = result["score"]

                found = True
                success_count += 1
                if len(success_examples) < 20:
                    success_examples.append(
                        f"  ✅ {name} ({city or '–'}) → {lat:.5f}, {lon:.5f} via {source}/{strategy}"
                    )
                print(f" → FOUND ({source}): {lat:.5f}, {lon:.5f}")
                break
            else:
                print(f" → not found")

        if not found:
            fail_count += 1
            existing_mff = props.get("missing_formal_fields", "")
            if "geocode_failed" not in existing_mff:
                new_mff = (existing_mff + ",geocode_failed").lstrip(",")
                props["missing_formal_fields"] = new_mff
            if len(failed_examples) < 20:
                failed_examples.append(
                    f"  ❌ {name} ({city or '–'}, dept={dept}, addr='{address or ''}')"
                )

        # Progress checkpoint every 25 features
        if (idx_num + 1) % 25 == 0:
            print(f"\n  --- Checkpoint: {idx_num+1}/{len(missing_indices)} done, {success_count} ok, {fail_count} fail ---\n")

    # Write updated file
    if not args.dry_run:
        print(f"\nWriting updated file to {output_path}...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print("\n[DRY-RUN] Not writing file.")

    # Summary
    total_processed = success_count + fail_count
    rate = (success_count / total_processed * 100) if total_processed > 0 else 0

    print("\n" + "=" * 70)
    print("GEOCODING SUMMARY")
    print("=" * 70)
    print(f"  Total features in file:     {total}")
    print(f"  Features needing geocoding:  {len(missing_indices)}")
    print(f"  Successfully geocoded:       {success_count}")
    print(f"  Failed / unchanged:          {fail_count}  (incl. {no_query_count} with no query)")
    print(f"  Success rate:               {rate:.1f}%")
    print()
    if success_examples:
        print("Sample successes:")
        for ex in success_examples:
            print(ex)
    print()
    if failed_examples:
        print("Sample failures:")
        for ex in failed_examples:
            print(ex)
    print()
    print(f"Output file: {output_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()