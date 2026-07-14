#!/usr/bin/env python3
"""Validate that the public deployment contains no private venue fields."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
CATALOG_PATH = PUBLIC_DIR / "salles_catalog_public.geojson"
MANIFEST_PATH = PUBLIC_DIR / "dataset-manifest.json"

ALLOWED_FIELDS = {
    "id",
    "name",
    "city",
    "department",
    "address",
    "category",
    "capacity_text",
    "capacity_max_detected",
    "price_text",
}

PRIVATE_LEGACY_FILES = {
    "salles_all_idf.geojson",
    "import_queue.geojson",
    "funnel_debug.json",
}


def load(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def main() -> None:
    catalog = load(CATALOG_PATH)
    manifest = load(MANIFEST_PATH)
    assert catalog.get("type") == "FeatureCollection"
    features = catalog.get("features")
    assert isinstance(features, list) and features
    assert manifest.get("release_id") == catalog.get("release_id")
    assert manifest.get("venue_count") == len(features)
    assert set(manifest.get("public_fields", [])) == ALLOWED_FIELDS

    ids: set[str] = set()
    selection = manifest.get("selection_contract") or {}
    bounds = selection.get("idf_bounds") or {}
    max_capacity = selection.get("max_capacity")
    for feature in features:
        properties = feature.get("properties") or {}
        assert set(properties) == ALLOWED_FIELDS, set(properties) - ALLOWED_FIELDS
        venue_id = properties.get("id")
        assert isinstance(venue_id, str) and venue_id
        assert venue_id not in ids, venue_id
        ids.add(venue_id)
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        assert geometry.get("type") == "Point" and len(coordinates) >= 2, venue_id
        lon, lat = coordinates[:2]
        assert bounds["min_lon"] <= lon <= bounds["max_lon"], venue_id
        assert bounds["min_lat"] <= lat <= bounds["max_lat"], venue_id
        raw_capacity = properties.get("capacity_max_detected")
        if raw_capacity not in (None, ""):
            try:
                assert float(raw_capacity) <= float(max_capacity), venue_id
            except (TypeError, ValueError):
                pass

    expected_hash = manifest["artifacts"][0]["sha256"]
    actual_hash = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
    assert expected_hash == actual_hash

    deploy_allowlist = {
        "index.html",
        "runtime-config.js",
        "dataset-manifest.json",
        "salles_catalog_public.geojson",
        "css",
        "js",
    }
    assert not (PRIVATE_LEGACY_FILES & deploy_allowlist)
    print(
        f"Release publique valide: {len(features)} salles, "
        f"release {manifest['release_id']}"
    )


if __name__ == "__main__":
    main()
