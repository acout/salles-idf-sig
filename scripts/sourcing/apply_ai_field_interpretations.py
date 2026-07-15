#!/usr/bin/env python3
"""Apply AI field interpretation results to public/import_queue.geojson.

This is a cautious second-pass enrichment layer:
- Reads field_interpret_results_*.jsonl produced by AI/web_extract readers.
- Fills missing obvious fields (capacity, price, contact, address, rental page).
- Keeps evidence/confidence metadata.
- Avoids overwriting existing better values and avoids risky generic PDF/listing pollution.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(v)).strip()


def blank(v: Any) -> bool:
    return norm(v) in {"", "0", "0.0", "None", "null", "—", "-"}


def is_pdf_or_catalog(url: str, page_type: str) -> bool:
    u = (url or "").lower()
    p = (page_type or "").lower()
    return u.endswith(".pdf") or "pdf" in u or "catalog" in p or "listing" in p


def simple_tokens(s: str) -> set[str]:
    stop = {"salle", "room", "studio", "espace", "le", "la", "les", "de", "du", "des", "l", "d", "n", "no", "n°"}
    return {t for t in re.findall(r"[a-z0-9]{3,}", norm(s).lower()) if t not in stop}


def evidence_matches_name(name: str, evidence: str) -> bool:
    toks = simple_tokens(name)
    if not toks:
        return False
    ev = norm(evidence).lower()
    return bool(toks & set(re.findall(r"[a-z0-9]{3,}", ev)))


def capacity_max_from_text(text: str) -> int:
    # Remove surface expressions before reading people counts, so 50m² doesn't become 50 people.
    no_surface = re.sub(r"\b\d+[\d,.]*\s?(?:m²|m2|sqm|square meters?)\b", " ", text or "", flags=re.I)
    ranges: list[int] = []
    for m in re.finditer(r"\b(\d+)\s?[-–]\s?(\d+)\s?(?:people|personnes|pers\.?|participants?)", no_surface, re.I):
        ranges.append(int(m.group(2)))
    # A direct capacity range is more specific than generic "up to" numbers
    # that can come from availability widgets or suggested alternatives.
    if ranges:
        return max(n for n in ranges if 0 < n < 1000)
    nums: list[int] = []
    for m in re.finditer(r"\b(?:jusqu(?:’|'|e)?à|up to|capacity|capacité)[^\n\.]{0,50}?(\d+)\s?(?:people|personnes|pers\.?|participants?)?", no_surface, re.I):
        nums.append(int(m.group(1)))
    for m in re.finditer(r"\b(\d+)\s?(?:people|personnes|pers\.?|participants?)\b", no_surface, re.I):
        nums.append(int(m.group(1)))
    nums = [n for n in nums if 0 < n < 1000]
    return max(nums) if nums else 0


def normalize_capacity_display(text: str) -> str:
    """Return a human-facing capacity string without marketplace noise.

    If a direct people range exists (e.g. 1-15 people), keep that as the primary
    capacity and keep surface m², but drop generic "up to" fragments that often
    come from widgets or alternatives.
    """
    raw = text or ""
    ranges = []
    for m in re.finditer(r"\b\d+\s?[-–]\s?\d+\s?(?:people|personnes|pers\.?|participants?)\b", raw, re.I):
        ranges.append(norm(m.group(0)))
    surfaces = []
    for m in re.finditer(r"\b\d+[\d,.]*\s?(?:m²|m2|sqm|square meters?)\b", raw, re.I):
        surfaces.append(norm(m.group(0)))
    if ranges:
        parts = list(dict.fromkeys(ranges + surfaces))
        return "; ".join(parts)
    return norm(raw)


def remove_missing(missing: str, filled: list[str]) -> str:
    items = [x.strip() for x in (missing or "").split(",") if x.strip()]
    aliases = {
        "capacity_text": {"capacity", "capacité", "capacities", "room_capacity", "capacité maximale", "capacité participants exacte", "surface"},
        "price_text": {"price", "prices", "pricing", "tarifs", "tarif", "rental_price", "tarifs détaillés", "exact_prices", "public_hire_prices", "tarifs location"},
        "contact": {"email", "phone", "contact", "contacts", "direct_contact", "email/téléphone direct", "contact location", "contact salle"},
        "address": {"address", "adresse", "exact_address", "street_address", "adresse complète du studio de montigny", "addressses", "addresses"},
        "specific_rental_page_url": {"rental_page_url", "rental_information", "rental_info", "rental_conditions", "offre de location"},
    }
    remove = set()
    for f in filled:
        remove |= aliases.get(f, {f})
    return ", ".join(x for x in items if x.lower() not in {r.lower() for r in remove})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geojson", default="public/import_queue.geojson")
    ap.add_argument("--results-dir", default="data/discovery_runs/ai_field_interpretation_20260621")
    ap.add_argument("--min-confidence", type=float, default=0.75)
    args = ap.parse_args()

    geo_path = ROOT / args.geojson
    data = json.loads(geo_path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    by_id = {f.get("properties", {}).get("candidate_id"): f for f in features}

    results = []
    for path in sorted((ROOT / args.results_dir).glob("field_interpret_results_*.jsonl")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            rec["_source_file"] = path.name
            rec["_source_line"] = line_no
            results.append(rec)

    updates = Counter()
    skipped = Counter()
    audit = []
    for rec in results:
        cid = rec.get("candidate_id")
        f = by_id.get(cid)
        if not f or not rec.get("success"):
            skipped["missing_feature_or_failed"] += 1
            continue
        p = f["properties"]
        fields = rec.get("fields") or {}
        evidence = rec.get("evidence") or {}
        conf = rec.get("confidence") or {}
        url = rec.get("url") or p.get("source_url") or ""
        page_type = p.get("page_type", "")
        risky_catalog = is_pdf_or_catalog(url, page_type)
        filled: list[str] = []

        def can_apply(field: str) -> bool:
            if float(conf.get(field) or 0) < args.min_confidence:
                return False
            if risky_catalog and field in {"capacity_text", "price_text", "contact", "address"}:
                return evidence_matches_name(p.get("name", ""), evidence.get(field, ""))
            return True

        # capacity
        cap = norm(fields.get("capacity_text"))
        if cap and can_apply("capacity_text") and (blank(p.get("capacity_text")) or not int(p.get("capacity_max_detected") or 0) or p.get("ai_interpreted_capacity_confidence")):
            p["capacity_text"] = normalize_capacity_display(cap)
            maxp = capacity_max_from_text(cap) or int(fields.get("capacity_max_detected") or 0)
            p["capacity_max_detected"] = maxp
            p["ai_interpreted_capacity_evidence"] = norm(evidence.get("capacity_text"))[:500]
            p["ai_interpreted_capacity_confidence"] = conf.get("capacity_text")
            filled.append("capacity_text")
            updates["capacity_text"] += 1

        # price
        price = norm(fields.get("price_text"))
        if price and can_apply("price_text") and (blank(p.get("price_text")) or p.get("ai_interpreted_price_confidence")):
            p["price_text"] = price
            p["ai_interpreted_price_evidence"] = norm(evidence.get("price_text"))[:500]
            p["ai_interpreted_price_confidence"] = conf.get("price_text")
            filled.append("price_text")
            updates["price_text"] += 1

        # contact
        contact = norm(fields.get("contact"))
        if contact and can_apply("contact") and blank(p.get("contact")):
            p["contact"] = contact
            p["ai_interpreted_contact_evidence"] = norm(evidence.get("contact"))[:500]
            p["ai_interpreted_contact_confidence"] = conf.get("contact")
            filled.append("contact")
            updates["contact"] += 1

        # address/city/postal
        address = norm(fields.get("address"))
        if address and can_apply("address") and (blank(p.get("address")) or p.get("address") == p.get("city")):
            p["address"] = address
            p["ai_interpreted_address_evidence"] = norm(evidence.get("address"))[:500]
            p["ai_interpreted_address_confidence"] = conf.get("address")
            filled.append("address")
            updates["address"] += 1
        if blank(p.get("city")) and norm(fields.get("city")):
            p["city"] = norm(fields.get("city"))
            filled.append("city")
            updates["city"] += 1
        if blank(p.get("postal_code")) and norm(fields.get("postal_code")):
            p["postal_code"] = norm(fields.get("postal_code"))
            filled.append("postal_code")
            updates["postal_code"] += 1

        # rental page/status/cons
        rental_url = norm(fields.get("specific_rental_page_url"))
        if rental_url and can_apply("specific_rental_page_url") and blank(p.get("specific_rental_page_url")):
            p["specific_rental_page_url"] = rental_url
            filled.append("specific_rental_page_url")
            updates["specific_rental_page_url"] += 1
        if norm(fields.get("rental_possible_status")) == "possible":
            p["rental_possible_status"] = "possible"
        cons = norm(fields.get("cons"))
        if cons and cons not in norm(p.get("cons")):
            p["cons"] = norm("; ".join(x for x in [p.get("cons"), cons] if x))

        if filled:
            p["formal_extraction_status"] = "ai_interpreted_enriched"
            p["formal_completeness_score"] = "interpreted"
            p["missing_formal_fields"] = remove_missing(p.get("missing_formal_fields", ""), filled)
            p["email_questions"] = p["missing_formal_fields"]
            p["ai_field_interpretation_source"] = rec.get("_source_file")
            p["ai_field_interpretation_checked_at"] = "2026-06-21"
            audit.append({"candidate_id": cid, "name": p.get("name"), "updated": filled, "url": url})

    geo_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    out_dir = ROOT / args.results_dir
    report = {
        "results": len(results),
        "updated_features": len(audit),
        "updates": dict(updates),
        "skipped": dict(skipped),
        "audit_samples": audit[:50],
    }
    (out_dir / "apply_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
