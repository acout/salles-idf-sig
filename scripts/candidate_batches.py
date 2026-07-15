#!/usr/bin/env python3
"""Load every venue produced by the two approved sourcing batches.

The import queue is already the output of the multi-source IDF batch and the
systematic south-suburb batch.  This module validates that hand-off contract;
it deliberately applies no quality, capacity, rental-status or score filter.
Those fields remain available to the cockpit so humans can filter and qualify
the complete set without losing a lead upstream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SOUTH_BATCH_SOURCE_FILE = "ai_classify_batch_0.jsonl"


def load_feature_collection(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise ValueError(f"FeatureCollection attendue: {path}")
    return value["features"]


def load_candidate_batch_features(path: Path) -> list[dict[str, Any]]:
    """Return the complete import queue after validating identities."""

    features = load_feature_collection(path)
    ids: set[str] = set()
    for index, feature in enumerate(features):
        properties = feature.get("properties") or {}
        venue_id = str(properties.get("candidate_id") or "").strip()
        name = str(properties.get("name") or "").strip()
        if not venue_id or not name:
            raise ValueError(f"Candidat incomplet à l'index {index}: {path}")
        if venue_id in ids:
            raise ValueError(f"candidate_id dupliqué: {venue_id}")
        ids.add(venue_id)
    return features


def batch_label(feature: dict[str, Any]) -> str:
    source_file = str((feature.get("properties") or {}).get("ai_source_file") or "")
    return "banlieue_sud" if source_file == SOUTH_BATCH_SOURCE_FILE else "sourcing_idf"


def source_fingerprint(feature: dict[str, Any]) -> str:
    payload = json.dumps(feature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capacity_bucket(feature: dict[str, Any]) -> str:
    raw = (feature.get("properties") or {}).get("capacity_max_detected")
    try:
        capacity = float(raw or 0)
    except (TypeError, ValueError):
        capacity = 0
    if capacity <= 0:
        return "unknown"
    return "small" if capacity <= 20 else "over_20"


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditer les batchs candidats chargés dans le cockpit")
    parser.add_argument("--import-queue", type=Path, default=Path("public/import_queue.geojson"))
    args = parser.parse_args()
    features = load_candidate_batch_features(args.import_queue)
    batches = Counter(batch_label(feature) for feature in features)
    capacities = Counter(capacity_bucket(feature) for feature in features)
    statuses = Counter(
        str((feature.get("properties") or {}).get("rental_possible_status") or "")
        for feature in features
    )
    print(json.dumps({
        "total": len(features),
        "batches": dict(sorted(batches.items())),
        "rental_statuses": dict(sorted(statuses.items())),
        "capacity_buckets": dict(sorted(capacities.items())),
        "with_coordinates": sum(
            1 for feature in features
            if (feature.get("geometry") or {}).get("coordinates") not in (None, [0, 0])
        ),
        "with_contact": sum(
            1 for feature in features
            if (feature.get("properties") or {}).get("contact")
        ),
        "missing_city": sum(
            1 for feature in features
            if not str((feature.get("properties") or {}).get("city") or "").strip()
        ),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
