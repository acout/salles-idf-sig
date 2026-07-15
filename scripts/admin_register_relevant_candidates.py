#!/usr/bin/env python3
"""Register every sourced candidate in the active Supabase campaign.

This is intentionally incremental: existing campaign rows, assignments, call
results and notes are never updated or deleted.  Only missing venue registry
and campaign rows are inserted.

Required environment variables:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from admin_bootstrap_supabase import ApiError, load_json, request
from candidate_batches import (
    batch_label,
    load_candidate_batch_features,
    source_fingerprint,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--campaign-id")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def verified_import_queue(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = load_json(manifest_path)
    artifact = next(
        (
            item for item in manifest.get("artifacts", [])
            if str(item.get("path") or "").endswith("/import_queue.geojson")
        ),
        None,
    )
    if artifact is None:
        raise ApiError("import_queue.geojson absent du manifeste privé")
    path = manifest_path.parent / Path(artifact["path"]).name
    if not path.is_file():
        raise ApiError(f"Artefact privé absent: {path}")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if checksum != artifact.get("sha256"):
        raise ApiError("Empreinte import_queue.geojson invalide")
    return load_candidate_batch_features(path)


def active_campaign_id(base: str, key: str) -> str:
    rows = request(
        base,
        key,
        "GET",
        "/rest/v1/workspace_state?select=active_campaign_id&singleton=eq.true&limit=1",
    )
    if not rows or not rows[0].get("active_campaign_id"):
        raise ApiError("Campagne active introuvable")
    return str(rows[0]["active_campaign_id"])


def post_batches(base: str, key: str, path: str, rows: list[dict[str, Any]], prefer: str) -> None:
    for start in range(0, len(rows), 100):
        request(
            base,
            key,
            "POST",
            path,
            rows[start:start + 100],
            extra_headers={"Prefer": prefer},
        )


def main() -> None:
    args = parse_args()
    manifest_path = args.private_manifest.resolve()
    selected = verified_import_queue(manifest_path)
    summary = {
        "selected": len(selected),
        "batches": dict(sorted(Counter(batch_label(feature) for feature in selected).items())),
        "with_coordinates": sum(
            1 for feature in selected
            if (feature.get("geometry") or {}).get("coordinates") not in (None, [0, 0])
        ),
        "with_contact": sum(
            1 for feature in selected
            if (feature.get("properties") or {}).get("contact")
        ),
        "includes_i_flow": any(
            (feature.get("properties") or {}).get("name") == "I-Flow"
            for feature in selected
        ),
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    base = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base.startswith("https://") or len(key) < 20:
        raise ApiError("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont requises")

    campaign_id = args.campaign_id or active_campaign_id(base, key)
    registry_rows = [
        {
            "venue_id": feature["properties"]["candidate_id"],
            "source_fingerprint": source_fingerprint(feature),
            "active": True,
        }
        for feature in selected
    ]
    campaign_rows = [
        {
            "campaign_id": campaign_id,
            "venue_id": feature["properties"]["candidate_id"],
        }
        for feature in selected
    ]
    post_batches(
        base,
        key,
        "/rest/v1/venue_registry?on_conflict=venue_id",
        registry_rows,
        "resolution=merge-duplicates,return=minimal",
    )
    post_batches(
        base,
        key,
        "/rest/v1/campaign_venues?on_conflict=campaign_id,venue_id",
        campaign_rows,
        "resolution=ignore-duplicates,return=minimal",
    )
    summary["campaign_id"] = campaign_id
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
