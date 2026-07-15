#!/usr/bin/env python3
"""Build a public venue catalog and a private, authenticated overlay.

The existing source artifacts are left untouched. Public output is written to
``public/``; private output is written outside that directory so the static
deployment cannot publish contacts or sourcing notes by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "public" / "salles_all_idf.geojson"
DEFAULT_IMPORT_QUEUE = ROOT / "public" / "import_queue.geojson"
DEFAULT_FUNNEL = ROOT / "public" / "funnel_debug.json"
DEFAULT_PUBLIC_DIR = ROOT / "public"
DEFAULT_PRIVATE_DIR = ROOT / ".private-dist"

PUBLIC_FIELDS = (
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
)

PRIVATE_FIELDS = (
    "website",
    "contact",
    "source_url",
    "pros",
    "cons",
    "confidence",
    "fit_score",
    "price_score",
    "last_checked",
)

RELEASE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
IDF_BOUNDS = {
    "min_lon": 1.4,
    "max_lon": 3.7,
    "min_lat": 48.0,
    "max_lat": 49.3,
}
MAX_CAPACITY = 20


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    path.write_text(payload + "\n", encoding="utf-8", newline="\n")


def validate_feature_collection(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise ValueError(f"{label}: FeatureCollection attendue")
    features = value.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"{label}: aucune feature")
    return features


def catalog_scope(feature: dict[str, Any]) -> str:
    """Classify every source venue without silently removing usable leads."""
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise ValueError("invalid_geometry")
    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, list)
        or len(coordinates) < 2
        or not all(isinstance(value, (int, float)) for value in coordinates[:2])
    ):
        raise ValueError("invalid_geometry")
    lon, lat = coordinates[:2]
    if not (
        IDF_BOUNDS["min_lon"] <= lon <= IDF_BOUNDS["max_lon"]
        and IDF_BOUNDS["min_lat"] <= lat <= IDF_BOUNDS["max_lat"]
    ):
        return "geocode_review"

    raw_capacity = (feature.get("properties") or {}).get("capacity_max_detected")
    if raw_capacity not in (None, ""):
        try:
            if float(raw_capacity) > MAX_CAPACITY:
                return "capacity_over_20"
        except (TypeError, ValueError):
            pass
    return "priority"


def artifact(path: Path, relative_path: str, required: bool, count: int) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": relative_path.replace("\\", "/"),
        "required": required,
        "schema_version": 1,
        "feature_count": count,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }


def build_release(args: argparse.Namespace) -> dict[str, Any]:
    source = load_json(args.source)
    source_features = validate_feature_collection(source, str(args.source))

    seen_ids: set[str] = set()
    public_features: list[dict[str, Any]] = []
    private_venues: list[dict[str, Any]] = []
    fingerprints: list[tuple[str, str]] = []
    scope_counts = {
        "priority": 0,
        "capacity_over_20": 0,
        "geocode_review": 0,
    }

    for index, feature in enumerate(source_features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"feature {index}: type invalide")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"feature {index}: properties absentes")
        try:
            scope = catalog_scope(feature)
        except ValueError as exc:
            raise ValueError(f"feature {index}: géométrie invalide") from exc
        scope_counts[scope] += 1
        venue_id = str(properties.get("id") or "").strip()
        if not venue_id:
            raise ValueError(f"feature {index}: id absent")
        if venue_id in seen_ids:
            raise ValueError(f"id dupliqué: {venue_id}")
        seen_ids.add(venue_id)

        geometry = feature.get("geometry")
        fingerprint = sha256_bytes(
            canonical_bytes({"geometry": geometry, "properties": properties})
        )
        fingerprints.append((venue_id, fingerprint))

        public_properties = {key: properties.get(key) for key in PUBLIC_FIELDS}
        public_properties["catalog_scope"] = scope
        public_features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": public_properties,
            }
        )

        private_record = {"id": venue_id, "source_fingerprint": fingerprint}
        private_record.update({key: properties.get(key) for key in PRIVATE_FIELDS})
        private_venues.append(private_record)

    fingerprint_payload = [
        {"id": venue_id, "source_fingerprint": fingerprint}
        for venue_id, fingerprint in sorted(fingerprints)
    ]
    dataset_checksum = sha256_bytes(canonical_bytes(fingerprint_payload))
    release_id = args.release_id or f"dataset-{dataset_checksum[:16]}"
    if not RELEASE_RE.fullmatch(release_id):
        raise ValueError("release_id invalide")

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    public_catalog = {
        "type": "FeatureCollection",
        "schema_version": 1,
        "release_id": release_id,
        "features": public_features,
    }
    public_catalog_path = args.public_dir / "salles_catalog_public.geojson"
    write_json(public_catalog_path, public_catalog)

    release_dir = args.private_dir / release_id
    private_overlay_path = release_dir / "venue_private_details.json"
    write_json(
        private_overlay_path,
        {
            "schema_version": 1,
            "release_id": release_id,
            "dataset_checksum": dataset_checksum,
            "venues": private_venues,
        },
    )

    private_artifacts = [
        artifact(
            private_overlay_path,
            f"{release_id}/venue_private_details.json",
            True,
            len(private_venues),
        )
    ]

    if args.import_queue.exists():
        import_queue = load_json(args.import_queue)
        import_features = validate_feature_collection(import_queue, str(args.import_queue))
        import_path = release_dir / "import_queue.geojson"
        write_json(import_path, import_queue)
        private_artifacts.append(
            artifact(
                import_path,
                f"{release_id}/import_queue.geojson",
                True,
                len(import_features),
            )
        )

    if args.funnel.exists():
        funnel = load_json(args.funnel)
        funnel_path = release_dir / "funnel_debug.json"
        write_json(funnel_path, funnel)
        funnel_count = len(funnel) if isinstance(funnel, list) else 1
        private_artifacts.append(
            artifact(
                funnel_path,
                f"{release_id}/funnel_debug.json",
                False,
                funnel_count,
            )
        )

    private_manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "generated_at": generated_at,
        "venue_count": len(public_features),
        "source_venue_count": len(source_features),
        "scope_counts": scope_counts,
        "excluded_counts": {"invalid_geometry": 0},
        "dataset_checksum": dataset_checksum,
        "artifacts": private_artifacts,
    }
    private_manifest_path = release_dir / "private-manifest.json"
    write_json(private_manifest_path, private_manifest)

    public_manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "generated_at": generated_at,
        "venue_count": len(public_features),
        "source_venue_count": len(source_features),
        "scope_counts": scope_counts,
        "excluded_counts": {"invalid_geometry": 0},
        "selection_contract": {
            "region": "Île-de-France",
            "default_scope": "priority",
            "max_capacity": MAX_CAPACITY,
            "idf_bounds": IDF_BOUNDS,
            "scope_definitions": {
                "priority": "coordonnées IDF et capacité maximale connue <= 20, ou capacité inconnue",
                "capacity_over_20": "coordonnées IDF et capacité maximale connue > 20",
                "geocode_review": "ville ou département IDF mais coordonnées hors de la zone attendue",
            },
        },
        "dataset_checksum": dataset_checksum,
        "public_fields": list(PUBLIC_FIELDS),
        "artifacts": [
            artifact(
                public_catalog_path,
                "salles_catalog_public.geojson",
                True,
                len(public_features),
            )
        ],
    }
    public_manifest_path = args.public_dir / "dataset-manifest.json"
    write_json(public_manifest_path, public_manifest)

    return {
        "release_id": release_id,
        "dataset_checksum": dataset_checksum,
        "venue_count": len(public_features),
        "public_manifest": str(public_manifest_path),
        "private_manifest": str(private_manifest_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--import-queue", type=Path, default=DEFAULT_IMPORT_QUEUE)
    parser.add_argument("--funnel", type=Path, default=DEFAULT_FUNNEL)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--private-dir", type=Path, default=DEFAULT_PRIVATE_DIR)
    parser.add_argument("--release-id")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build_release(parse_args()), ensure_ascii=False, indent=2))
