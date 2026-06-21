#!/usr/bin/env python3
"""Prepare batches for AI field interpretation of imported venue candidates.

This is a second-pass AI layer after adaptive classification/conversion.
It targets imported candidates with missing/weak fields and asks an AI reader
(via web_extract in subagents/Hermes) to re-read the associated web page and
extract obvious fields with evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]

MISSING_KEYS = ["capacity", "price", "email", "phone", "address", "postal_code", "city"]


def is_blank(v) -> bool:
    return v is None or str(v).strip() in {"", "0", "0.0", "—", "-", "None", "null"}


def best_url(p: dict) -> str:
    for k in ["specific_rental_page_url", "source_url", "website"]:
        u = (p.get(k) or "").strip()
        if u.startswith("http"):
            return u
    return ""


def missing_fields(p: dict) -> list[str]:
    existing = (p.get("missing_formal_fields") or "")
    out = {x.strip() for x in existing.split(",") if x.strip()}
    if is_blank(p.get("capacity_text")) or str(p.get("capacity_max_detected") or "0") == "0":
        out.add("capacity")
    if is_blank(p.get("price_text")):
        out.add("price")
    contact = p.get("contact") or ""
    if "@" not in contact:
        out.add("email")
    if not any(ch.isdigit() for ch in contact):
        out.add("phone")
    if is_blank(p.get("address")) or p.get("address") == p.get("city"):
        out.add("address")
    if is_blank(p.get("city")):
        out.add("city")
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="public/import_queue.geojson")
    ap.add_argument("--out-dir", default="data/discovery_runs/ai_field_interpretation_20260621")
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    data = json.loads((ROOT / args.input).read_text(encoding="utf-8"))
    tasks = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        url = best_url(p)
        miss = missing_fields(p)
        if not url or not miss:
            continue
        # prioritize pages where fields are likely extractable/actionable
        priority = 0
        if "capacity" in miss:
            priority += 5
        if "price" in miss:
            priority += 4
        if "email" in miss or "phone" in miss:
            priority += 3
        if p.get("rental_possible_status") == "possible":
            priority += 2
        if p.get("source_reliability") in {"S4", "S3"}:
            priority += 2
        tasks.append({
            "candidate_id": p.get("candidate_id"),
            "name": p.get("name"),
            "city": p.get("city"),
            "department": p.get("department"),
            "current": {
                "capacity_text": p.get("capacity_text"),
                "capacity_max_detected": p.get("capacity_max_detected"),
                "price_text": p.get("price_text"),
                "contact": p.get("contact"),
                "address": p.get("address"),
                "city": p.get("city"),
                "postal_code": p.get("postal_code"),
                "specific_rental_page_url": p.get("specific_rental_page_url"),
                "source_url": p.get("source_url"),
            },
            "url": url,
            "url_domain": urlparse(url).netloc,
            "missing_fields": miss,
            "page_type": p.get("page_type"),
            "source_reliability": p.get("source_reliability"),
            "priority": priority,
        })

    tasks.sort(key=lambda x: (-x["priority"], x["url_domain"], x["name"] or ""))
    if args.limit:
        tasks = tasks[: args.limit]

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tasks_all.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

    batches = []
    for i in range(0, len(tasks), args.batch_size):
        batch = tasks[i : i + args.batch_size]
        path = out_dir / f"field_interpret_batch_{len(batches):02d}.json"
        path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        batches.append(str(path.relative_to(ROOT)))

    report = {
        "tasks": len(tasks),
        "batches": len(batches),
        "batch_files": batches,
        "top_missing_counts": {},
    }
    for t in tasks:
        for m in t["missing_fields"]:
            report["top_missing_counts"][m] = report["top_missing_counts"].get(m, 0) + 1
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
