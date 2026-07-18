#!/usr/bin/env python3
"""Import the 253 legacy sourced candidates into the Supabase inbox.

The import is deterministic and intentionally insert-only on conflicts: a rerun
must never overwrite a human review, visibility decision, assignment, or call
history. Service-role writes rely on stable keys and database uniqueness rather
than the authenticated-user operation receipt table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from admin_bootstrap_supabase import ApiError, request
from admin_register_relevant_candidates import (
    active_campaign_id,
    post_batches,
    verified_import_queue,
)
from candidate_batches import batch_label, load_candidate_batch_features, source_fingerprint


ROOT = Path(__file__).resolve().parents[1]
LEGACY_NAMESPACE = uuid.UUID("596b1178-cc8c-4a7a-8fd6-b675c1a648f6")
EXPECTED_LEGACY_COUNT = 253
IDF_DEPARTMENTS = {"75", "92", "93", "94", "77", "78", "91", "95"}
CANONICAL_FIELDS = (
    "name",
    "address",
    "city",
    "department",
    "lat",
    "lon",
    "capacity_max",
    "capacity_text",
    "price_text",
    "website_url",
    "contact_text",
    "source_url",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--private-manifest", type=Path)
    source.add_argument("--import-queue", type=Path)
    parser.add_argument("--campaign-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quarantine-output", type=Path)
    return parser.parse_args()


def clean_text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    if not result:
        return None
    return result[:limit] if limit else result


def finite_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def positive_integer(value: Any) -> int | None:
    number = finite_number(value)
    if number is None or number <= 0:
        return None
    return int(round(number))


def http_url(value: Any) -> str | None:
    result = clean_text(value, 2000)
    return result if result and result.lower().startswith(("http://", "https://")) else None


def observed_at(value: Any) -> str:
    text = clean_text(value)
    if text:
        try:
            if len(text) == 10:
                return datetime.combine(date.fromisoformat(text), datetime.min.time(), timezone.utc).isoformat()
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def stable_hash(*parts: Any) -> str:
    material = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def stable_uuid(kind: str, key: str) -> str:
    return str(uuid.uuid5(LEGACY_NAMESPACE, f"{kind}:{key}"))


def evidence_confidence(properties: dict[str, Any], field: str) -> int:
    aliases = {
        "capacity_max": "ai_interpreted_capacity_confidence",
        "capacity_text": "ai_interpreted_capacity_confidence",
        "price_text": "ai_interpreted_price_confidence",
        "contact_text": "ai_interpreted_contact_confidence",
    }
    raw = properties.get(aliases.get(field, "source_confidence"), properties.get("confidence_score", 0.5))
    number = finite_number(raw)
    if number is None:
        return 50
    if number <= 1:
        number *= 100
    return max(0, min(100, int(round(number))))


def legacy_batch_key(properties: dict[str, Any]) -> str:
    return "banlieue_sud" if clean_text(properties.get("ai_source_file")) == "ai_classify_batch_0.jsonl" else "sourcing_idf"


def score(value: Any) -> int | None:
    number = finite_number(value)
    if number is None:
        return None
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, int(round(number))))


def legacy_feature_to_rows(feature: dict[str, Any], row_number: int = 0) -> dict[str, Any]:
    properties = feature.get("properties") or {}
    linked_venue_id = clean_text(properties.get("candidate_id") or properties.get("id"), 500)
    name = clean_text(properties.get("name"), 200)
    if not linked_venue_id:
        raise ValueError("identifiant historique absent")
    if not name:
        raise ValueError("nom absent")

    department = clean_text(properties.get("department"), 2)
    if department and department not in IDF_DEPARTMENTS:
        raise ValueError(f"département invalide: {department}")

    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    lon = finite_number(properties.get("lon"))
    lat = finite_number(properties.get("lat"))
    if len(coordinates) >= 2:
        lon = finite_number(coordinates[0]) if finite_number(coordinates[0]) not in (None, 0) else lon
        lat = finite_number(coordinates[1]) if finite_number(coordinates[1]) not in (None, 0) else lat
    if lon == 0 or lat == 0:
        lon = None
        lat = None

    source_url = http_url(properties.get("source_url") or properties.get("specific_rental_page_url"))
    website_url = http_url(properties.get("website_url") or properties.get("website"))
    candidate_id = stable_uuid("candidate", linked_venue_id)
    legacy_digest = stable_hash(linked_venue_id)
    external_key = f"legacy_candidate.{legacy_digest}"
    seen_at = observed_at(
        properties.get("last_seen_at")
        or properties.get("formal_scrape_checked_at")
        or properties.get("ai_field_interpretation_checked_at")
    )

    candidate = {
        "candidate_id": candidate_id,
        "schema_version": 1,
        "external_key": external_key,
        "legacy_venue_id": linked_venue_id,
        "linked_venue_id": linked_venue_id,
        "name": name,
        "address": clean_text(properties.get("address"), 500),
        "city": clean_text(properties.get("city"), 160),
        "department": department,
        "lat": lat,
        "lon": lon,
        "capacity_max": positive_integer(
            properties.get("capacity_max")
            if properties.get("capacity_max") not in (None, "")
            else properties.get("capacity_max_detected")
        ),
        "capacity_text": clean_text(properties.get("capacity_text"), 500),
        "price_text": clean_text(properties.get("price_text"), 500),
        "website_url": website_url,
        "contact_text": clean_text(properties.get("contact_text") or properties.get("contact"), 1000),
        "source_url": source_url,
        "category": clean_text(properties.get("category"), 300),
        "source_batch_key": legacy_batch_key(properties),
        "rental_status": clean_text(properties.get("rental_possible_status"))
        if clean_text(properties.get("rental_possible_status")) in {"possible", "unclear"}
        else "unknown",
        "confidence": score(properties.get("source_confidence") or properties.get("confidence_score")),
        "fit_score": score(properties.get("actionability_score") or properties.get("fit_beyond_score")),
        "price_score": score(properties.get("price_score")),
        "pros": clean_text(properties.get("rental_positive_signals") or properties.get("description"), 4000),
        "cons": clean_text(
            " · ".join(
                part for part in [
                    "Location à confirmer" if properties.get("rental_possible_status") == "unclear" else "",
                    clean_text(properties.get("missing_formal_fields")) or "",
                ] if part
            ),
            4000,
        ),
        "last_checked": clean_text(
            properties.get("formal_scrape_checked_at") or properties.get("last_seen_at"), 10
        ),
        "page_type": clean_text(properties.get("page_type"), 200),
        "review_status": "unreviewed",
        "cockpit_visible": True,
    }

    observation_key = f"legacy_observation.{stable_hash(linked_venue_id, source_url, seen_at)}"
    observation_id = stable_uuid("observation", observation_key)
    observation = {
        "observation_id": observation_id,
        "candidate_id": candidate_id,
        "source_type": "file",
        "source_url": source_url,
        "canonical_url": source_url,
        "observed_at": seen_at,
        "title": name,
        "excerpt": clean_text(properties.get("evidence_text") or properties.get("description"), 4000),
        "external_key": observation_key,
    }

    evidence: list[dict[str, Any]] = []
    for field in CANONICAL_FIELDS:
        value = candidate.get(field)
        if value is None:
            continue
        evidence_key = f"legacy_evidence.{stable_hash(linked_venue_id, field)}"
        evidence.append(
            {
                "evidence_id": stable_uuid("evidence", evidence_key),
                "candidate_id": candidate_id,
                "observation_id": observation_id,
                "field_name": field,
                "value": value,
                "confidence": evidence_confidence(properties, field),
                "resolution_status": "accepted",
                "resolved_at": seen_at,
                "external_key": evidence_key,
            }
        )

    event_key = f"legacy_event.{legacy_digest}"
    event = {
        "candidate_id": candidate_id,
        "event_type": "imported",
        "payload": {
            "source": "legacy_import_queue",
            "row_number": row_number,
            "linked_venue_id": linked_venue_id,
        },
        "external_key": event_key,
    }
    registry = {
        "venue_id": linked_venue_id,
        "source_fingerprint": source_fingerprint(feature),
        "active": True,
    }
    return {
        "candidate": candidate,
        "observation": observation,
        "evidence": evidence,
        "event": event,
        "registry": registry,
    }


def build_import_payload(features: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    payload = {"candidates": [], "observations": [], "evidence": [], "events": [], "registry": []}
    quarantine: list[dict[str, Any]] = []
    seen_venue_ids: set[str] = set()
    for row_number, feature in enumerate(features, start=1):
        try:
            rows = legacy_feature_to_rows(feature, row_number)
            linked_venue_id = rows["candidate"]["linked_venue_id"]
            if linked_venue_id in seen_venue_ids:
                raise ValueError("identifiant historique dupliqué")
            seen_venue_ids.add(linked_venue_id)
            payload["candidates"].append(rows["candidate"])
            payload["observations"].append(rows["observation"])
            payload["evidence"].extend(rows["evidence"])
            payload["events"].append(rows["event"])
            payload["registry"].append(rows["registry"])
        except (KeyError, TypeError, ValueError) as exc:
            properties = feature.get("properties") or {}
            quarantine.append(
                {
                    "row_number": row_number,
                    "candidate_id": clean_text(properties.get("candidate_id")),
                    "name": clean_text(properties.get("name")),
                    "error": str(exc),
                }
            )
    return payload, quarantine


def load_features(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.private_manifest:
        return verified_import_queue(args.private_manifest.resolve())
    return load_candidate_batch_features(args.import_queue.resolve())


def import_summary(
    features: list[dict[str, Any]],
    payload: dict[str, list[dict[str, Any]]],
    quarantine: list[dict[str, Any]],
) -> dict[str, Any]:
    linked_ids = [row["linked_venue_id"] for row in payload["candidates"]]
    return {
        "input_count": len(features),
        "candidate_count": len(payload["candidates"]),
        "observation_count": len(payload["observations"]),
        "evidence_count": len(payload["evidence"]),
        "quarantine_count": len(quarantine),
        "unique_legacy_ids": len(set(linked_ids)),
        "batches": dict(sorted(Counter(batch_label(feature) for feature in features).items())),
        "includes_i_flow": "venue_venue_i-flow.fr_i_arcueil" in linked_ids,
    }


def verify_remote(base: str, key: str, campaign_id: str, expected_ids: set[str]) -> None:
    candidates = request(
        base,
        key,
        "GET",
        "/rest/v1/sourcing_candidates?select=candidate_id,legacy_venue_id,linked_venue_id,external_key,cockpit_visible"
        "&external_key=like.legacy_candidate.%25&limit=1000",
    )
    remote_ids = {str(row.get("legacy_venue_id")) for row in candidates or []}
    if remote_ids != expected_ids:
        missing = sorted(expected_ids - remote_ids)[:5]
        extra = sorted(remote_ids - expected_ids)[:5]
        raise ApiError(f"Parité sourcing invalide: manquants={missing}, supplémentaires={extra}")
    campaign_rows = request(
        base,
        key,
        "GET",
        f"/rest/v1/campaign_venues?select=venue_id&campaign_id=eq.{campaign_id}&limit=1000",
    )
    campaign_ids = {str(row.get("venue_id")) for row in campaign_rows or []}
    missing_campaign = sorted(expected_ids - campaign_ids)
    if missing_campaign:
        raise ApiError(f"Lignes de campagne absentes: {missing_campaign[:5]}")


def main() -> None:
    args = parse_args()
    features = load_features(args)
    payload, quarantine = build_import_payload(features)
    summary = import_summary(features, payload, quarantine)

    if args.quarantine_output and quarantine:
        output = args.quarantine_output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(quarantine, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["quarantine_output"] = str(output)

    if len(features) != EXPECTED_LEGACY_COUNT or len(payload["candidates"]) != EXPECTED_LEGACY_COUNT:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise ApiError(f"Import legacy incomplet: {len(payload['candidates'])}/{EXPECTED_LEGACY_COUNT}")
    if quarantine:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise ApiError("Des lignes legacy ont été mises en quarantaine")
    if not summary["includes_i_flow"]:
        raise ApiError("iFlow Arcueil absente de l'import")
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    base = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base.startswith("https://") or len(key) < 20:
        raise ApiError("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont requises")
    campaign_id = args.campaign_id or active_campaign_id(base, key)
    campaign_rows = [{"campaign_id": campaign_id, "venue_id": row["linked_venue_id"]} for row in payload["candidates"]]

    post_batches(base, key, "/rest/v1/venue_registry?on_conflict=venue_id", payload["registry"],
        "resolution=ignore-duplicates,return=minimal")
    post_batches(base, key, "/rest/v1/campaign_venues?on_conflict=campaign_id,venue_id", campaign_rows,
        "resolution=ignore-duplicates,return=minimal")
    post_batches(base, key, "/rest/v1/sourcing_candidates?on_conflict=candidate_id", payload["candidates"],
        "resolution=ignore-duplicates,return=minimal")
    post_batches(base, key, "/rest/v1/source_observations?on_conflict=external_key", payload["observations"],
        "resolution=ignore-duplicates,return=minimal")
    post_batches(base, key, "/rest/v1/candidate_evidence?on_conflict=external_key", payload["evidence"],
        "resolution=ignore-duplicates,return=minimal")
    post_batches(base, key, "/rest/v1/sourcing_events?on_conflict=external_key", payload["events"],
        "resolution=ignore-duplicates,return=minimal")

    expected_ids = {row["linked_venue_id"] for row in payload["candidates"]}
    verify_remote(base, key, campaign_id, expected_ids)
    summary["campaign_id"] = campaign_id
    summary["remote_verified"] = True
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
