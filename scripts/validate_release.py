#!/usr/bin/env python3
"""Validate that the public deployment contains no private venue fields."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_public_private_release import catalog_scope


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
PRIVATE_DIR = ROOT / ".private-dist"
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
    "catalog_scope",
}

CATALOG_SCOPES = {"priority", "capacity_over_20", "geocode_review"}

PRIVATE_LEGACY_FILES = {
    "salles_all_idf.geojson",
    "import_queue.geojson",
    "funnel_debug.json",
}


def load(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def scope_fixture(lon: float, lat: float, capacity=None) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"capacity_max_detected": capacity},
    }


def validate_scope_boundaries() -> None:
    assert catalog_scope(scope_fixture(2.35, 48.85, 20)) == "priority"
    assert catalog_scope(scope_fixture(2.35, 48.85, None)) == "priority"
    assert catalog_scope(scope_fixture(2.35, 48.85, "inconnue")) == "priority"
    assert catalog_scope(scope_fixture(2.35, 48.85, 21)) == "capacity_over_20"
    assert catalog_scope(scope_fixture(0.0, 0.0, 10)) == "geocode_review"
    try:
        catalog_scope({"type": "Feature", "geometry": None, "properties": {}})
    except ValueError:
        pass
    else:
        raise AssertionError("Une géométrie invalide doit bloquer la release")


def main() -> None:
    validate_scope_boundaries()
    catalog = load(CATALOG_PATH)
    manifest = load(MANIFEST_PATH)
    assert catalog.get("type") == "FeatureCollection"
    features = catalog.get("features")
    assert isinstance(features, list) and features
    assert manifest.get("release_id") == catalog.get("release_id")
    assert manifest.get("venue_count") == len(features)
    assert manifest.get("source_venue_count") == len(features), (
        "Toutes les salles sources doivent rester accessibles dans le catalogue"
    )
    assert set(manifest.get("public_fields", [])) == ALLOWED_FIELDS

    ids: set[str] = set()
    selection = manifest.get("selection_contract") or {}
    bounds = selection.get("idf_bounds") or {}
    max_capacity = selection.get("max_capacity")
    assert selection.get("default_scope") == "priority"
    observed_scope_counts = {scope: 0 for scope in CATALOG_SCOPES}
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
        in_idf_bounds = (
            bounds["min_lon"] <= lon <= bounds["max_lon"]
            and bounds["min_lat"] <= lat <= bounds["max_lat"]
        )
        scope = properties.get("catalog_scope")
        assert scope in CATALOG_SCOPES, (venue_id, scope)
        observed_scope_counts[scope] += 1
        raw_capacity = properties.get("capacity_max_detected")
        numeric_capacity = None
        if raw_capacity not in (None, ""):
            try:
                numeric_capacity = float(raw_capacity)
            except (TypeError, ValueError):
                pass
        if scope == "priority":
            assert in_idf_bounds, venue_id
            assert numeric_capacity is None or numeric_capacity <= float(max_capacity), venue_id
        elif scope == "capacity_over_20":
            assert in_idf_bounds, venue_id
            assert numeric_capacity is not None and numeric_capacity > float(max_capacity), venue_id
        else:
            assert not in_idf_bounds, venue_id

    assert manifest.get("scope_counts") == observed_scope_counts

    release_dir = PRIVATE_DIR / manifest["release_id"]
    private_manifest = load(release_dir / "private-manifest.json")
    private_overlay = load(release_dir / "venue_private_details.json")
    assert private_manifest.get("release_id") == manifest.get("release_id")
    assert private_manifest.get("dataset_checksum") == manifest.get("dataset_checksum")
    private_ids = {venue.get("id") for venue in private_overlay.get("venues", [])}
    assert None not in private_ids
    assert private_ids == ids, "Les overlays public et privé doivent couvrir les mêmes salles"

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
