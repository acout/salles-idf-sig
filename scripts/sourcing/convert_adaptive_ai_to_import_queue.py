#!/usr/bin/env python3
"""Convert adaptive AI venue-classification JSONL chunks into app import_queue.

This is the production converter for the adaptive workflow where AI reads page content,
classifies single venue pages, and extracts individual venues from multi-venue
listings/PDF/catalogues.

Inputs under data/discovery_runs/<run_id>/:
  - venue_entities.json / venue_entities_curated.json
  - observations_classified.json
  - ai_classify_retry_chunk_*.jsonl

Outputs:
  - public/import_queue.geojson              (overwritten by design)
  - public/funnel_debug.json                 (overwritten by design)
  - data/import_queue/import_queue_<tag>.csv
  - data/import_queue/report_<tag>.json

Protected canonical files are not touched.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
IDF_DEPTS = {"75", "77", "78", "91", "92", "93", "94", "95"}
IDF_CITY_DEPT = {
    "paris": "75", "cachan": "94", "chatillon": "92", "châtillon": "92", "montrouge": "92",
    "bagneux": "92", "arcueil": "94", "malakoff": "92", "villejuif": "94", "bourg-la-reine": "92",
    "fontenay-aux-roses": "92", "sceaux": "92", "clamart": "92", "meudon": "92", "vanves": "92",
    "gentilly": "94", "kremlin-bicetre": "94", "le kremlin-bicetre": "94", "le kremlin-bicêtre": "94",
    "ivry-sur-seine": "94", "vitry-sur-seine": "94", "choisy-le-roi": "94", "creteil": "94", "créteil": "94",
    "saint-maur-des-fosses": "94", "saint-maur-des-fossés": "94", "alfortville": "94", "vincennes": "94",
    "boulogne-billancourt": "92", "issy-les-moulineaux": "92", "puteaux": "92", "nanterre": "92",
    "saint-ouen-sur-seine": "93", "aubervilliers": "93", "montreuil": "93", "bobigny": "93", "pantin": "93",
    "orly": "94", "masssy": "91", "massy": "91", "orsay": "91", "antony": "92", "fresnes": "94",
    "serris": "77", "versailles": "78", "saint-germain-en-laye": "78",
}
NON_VENUE_CATEGORIES = {
    "agenda_planning", "pdf_document", "procedure_form", "event_page", "blog_article",
    "other_non_venue", "scrape_failed", "out_of_region", "booking_search_app_fetch_failed",
    "rental_advice_article", "class_detail_page", "health_service_page", "association_admin_page",
}
RENTAL_POSITIVE_CATEGORIES = {
    "venue_with_rental_page", "venue_rental_mentioned", "official_rental_page",
    "official_rental_page_multi_space", "official_rental_page_single_space",
    "directory_rental_venue_page", "marketplace_venue_listing", "venue_with_extracted_rental_spaces",
}
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:(?:\+33|0)\s*[1-9](?:[\s.\-]*\d{2}){4})")
POSTAL_RE = re.compile(r"\b(75\d{3}|77\d{3}|78\d{3}|91\d{3}|92\d{3}|93\d{3}|94\d{3}|95\d{3})\b")


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value).replace("\x00", " ")).strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm_text(value).lower()).strip("_")[:90]


def h(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:10]


def first(*values: Any) -> str:
    for value in values:
        txt = norm_text(value)
        if txt and txt.lower() not in {"none", "null", "[]", "{}", "—", "-"}:
            return txt
    return ""


def dictish_missing(record: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Subagents sometimes used missing_info as extracted-info dict. Normalize both shapes."""
    mi = record.get("missing_info")
    extracted: dict[str, str] = {}
    missing: list[str] = []
    if isinstance(mi, dict):
        extracted = {str(k): norm_text(v) for k, v in mi.items() if norm_text(v)}
    elif isinstance(mi, list):
        missing = [norm_text(x) for x in mi if norm_text(x)]
    elif isinstance(mi, str) and mi.strip():
        missing = [mi.strip()]
    return extracted, missing


def normalize_missing(fields: dict[str, str], missing: list[str]) -> list[str]:
    required = {
        "address": ["address", "adresse"],
        "city": ["city", "ville"],
        "postal_code": ["postal_code", "cp", "code_postal"],
        "phone": ["phone", "telephone", "téléphone"],
        "email": ["email", "mail"],
        "price": ["price", "pricing", "tarif", "tarifs", "prices"],
        "capacity": ["capacity", "capacité", "capacities"],
        "rental_page_url": ["rental_page_url", "rental_page", "location_url"],
    }
    present = {k for k, v in fields.items() if norm_text(v)}
    out = set(missing)
    for canonical, aliases in required.items():
        if not any(alias in present for alias in aliases):
            out.add(canonical)
    return sorted(out)


def dept_from_fields(city: str, postal_code: str, parent_dept: str = "") -> str:
    pc = POSTAL_RE.search(postal_code or "")
    if pc:
        return pc.group(1)[:2]
    c = norm_text(city).lower()
    if c in IDF_CITY_DEPT:
        return IDF_CITY_DEPT[c]
    if parent_dept in IDF_DEPTS:
        return parent_dept
    return ""


def is_in_scope(city: str, postal_code: str, dept: str, reason: str) -> bool:
    reason_l = norm_text(reason).lower()
    if "hors île-de-france" in reason_l or "hors ile-de-france" in reason_l or "hors idf" in reason_l:
        return False
    if dept in IDF_DEPTS:
        return True
    pc = POSTAL_RE.search(postal_code or "")
    if pc and pc.group(1)[:2] in IDF_DEPTS:
        return True
    c = norm_text(city).lower()
    return c in IDF_CITY_DEPT


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_ai_records(run_dir: Path) -> list[dict[str, Any]]:
    files = sorted(run_dir.glob("ai_classify_retry_chunk_*.jsonl"))
    records: list[dict[str, Any]] = []
    for file in files:
        for line_no, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                rec["_source_ai_file"] = file.name
                rec["_source_ai_line"] = line_no
                records.append(rec)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSONL {file}:{line_no}: {exc}") from exc
    return records


def build_indexes(run_dir: Path):
    entities = load_json(run_dir / "venue_entities.json", [])
    curated = load_json(run_dir / "venue_entities_curated.json", [])
    observations = load_json(run_dir / "observations_classified.json", [])
    obs_by_id = {o.get("observation_id"): o for o in observations}
    ent_by_id = {e.get("venue_entity_id"): e for e in entities + curated}
    return entities, curated, obs_by_id, ent_by_id


def parent_context(rec: dict[str, Any], ent_by_id: dict[str, dict], obs_by_id: dict[str, dict]) -> dict[str, Any]:
    eid = rec.get("venue_entity_id", "")
    ent = ent_by_id.get(eid, {})
    obs = obs_by_id.get(ent.get("primary_observation_id", ""), {})
    lat = first(ent.get("canonical_lat"), obs.get("candidate_lat_hint"))
    lon = first(ent.get("canonical_lon"), obs.get("candidate_lon_hint"))
    return {"entity": ent, "obs": obs, "lat": lat, "lon": lon}


def extract_contact(text: str) -> tuple[str, str]:
    email = EMAIL_RE.search(text or "")
    phone = PHONE_RE.search(text or "")
    return (phone.group(0) if phone else "", email.group(0) if email else "")


def feature_from_fields(*, candidate_id: str, fields: dict[str, str], parent: dict[str, Any], rec: dict[str, Any], source_kind: str) -> dict[str, Any] | None:
    ent, obs = parent["entity"], parent["obs"]
    category = norm_text(rec.get("page_category"))
    reason = norm_text(rec.get("classification_reason"))
    source_url = first(rec.get("url"), ent.get("primary_source_url"), obs.get("source_url"), ent.get("official_website_url"))
    parent_name = first(rec.get("venue_name"), rec.get("canonical_name"), ent.get("canonical_name"), obs.get("source_title"))

    name = first(fields.get("name"), fields.get("venue_name"), rec.get("venue_name"), parent_name)
    address = first(fields.get("address"), fields.get("adresse"), obs.get("candidate_address_hint"), ent.get("canonical_city"))
    city = first(fields.get("city"), fields.get("ville"), obs.get("candidate_city_hint"), ent.get("canonical_city"))
    postal_match = POSTAL_RE.search(address or "")
    postal = first(fields.get("postal_code"), fields.get("cp"), fields.get("code_postal"), postal_match.group(1) if postal_match else "")
    dept = dept_from_fields(city, postal, first(ent.get("canonical_department"), obs.get("candidate_department_hint")))

    if not name:
        return None
    if not is_in_scope(city, postal, dept, reason):
        return None

    contact_blob = " ".join(norm_text(v) for v in fields.values())
    phone = first(fields.get("phone"), fields.get("telephone"), fields.get("téléphone"))
    email = first(fields.get("email"), fields.get("mail"))
    if not phone or not email:
        p2, e2 = extract_contact(contact_blob)
        phone = phone or p2
        email = email or e2
    contact = " — ".join(x for x in [phone, email] if x)

    price = first(fields.get("price"), fields.get("pricing"), fields.get("tarif"), fields.get("tarifs"), fields.get("prices"))
    capacity = first(fields.get("capacity"), fields.get("capacité"), fields.get("capacities"))
    surface = fields.get("surface")
    if surface and surface not in capacity:
        capacity = first(capacity, surface)
    rental_page = first(fields.get("rental_page_url"), fields.get("rental_page"), rec.get("rental_page_url"), source_url if rec.get("is_rental_page") else "")
    website = first(fields.get("website"), fields.get("site"), ent.get("official_website_url"), source_url)

    _, explicit_missing = dictish_missing(rec)
    if source_kind == "single":
        missing_source = explicit_missing
    else:
        raw_missing = fields.get("missing_info")
        missing_source = raw_missing if isinstance(raw_missing, list) else []
    missing = normalize_missing({
        "address": address, "city": city, "postal_code": postal, "phone": phone, "email": email,
        "price": price, "capacity": capacity, "rental_page_url": rental_page,
    }, missing_source)

    rental_status = "possible" if (rec.get("is_rental_page") or category in RENTAL_POSITIVE_CATEGORIES or rental_page) else "unclear"
    fit_score = 55 + (20 if rental_status == "possible" else 0) + (8 if contact else 0) + (5 if price else 0) + (5 if capacity else 0)
    if source_kind == "extracted_from_listing":
        fit_score -= 5
    fit_score = max(0, min(100, fit_score))

    lat = first(fields.get("lat"), fields.get("latitude"), parent.get("lat"))
    lon = first(fields.get("lon"), fields.get("lng"), fields.get("longitude"), parent.get("lon"))
    coords = [float(lon), float(lat)] if lat and lon else [0, 0]

    evidence = first(fields.get("evidence_quote"), reason)
    page_type = category or first(ent.get("primary_page_type"), obs.get("page_type"), "ai_adaptive")
    reliability = first(ent.get("primary_source_reliability"), obs.get("source_reliability"), "S3")

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coords},
        "properties": {
            "candidate_id": candidate_id,
            "name": norm_text(name),
            "city": norm_text(city),
            "department": dept,
            "address": norm_text(" ".join(x for x in [address, postal, city] if x and x not in address)),
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
            "category": norm_text(page_type.replace("_", " ")),
            "capacity_text": norm_text(capacity),
            "capacity_max_detected": 0,
            "price_text": norm_text(price),
            "price_score": 0,
            "website": norm_text(website),
            "contact": norm_text(contact),
            "source_url": norm_text(source_url),
            "source_domain": norm_text(obs.get("source_domain", "")),
            "source_confidence": 0.75 if source_kind == "single" else 0.65,
            "fit_beyond_score": fit_score,
            "confidence_score": 0.75 if source_kind == "single" else 0.65,
            "actionability_score": fit_score,
            "formal_completeness_score": f"{8-len(missing)}/8",
            "formal_extraction_status": "ai_adaptive_extracted",
            "formal_scrape_checked_at": datetime.now().isoformat()[:10],
            "formal_scrape_content_type": page_type,
            "is_aggregator": "no",
            "aggregator_domain": "",
            "rental_possible_status": rental_status,
            "rental_possible_confidence": 0.85 if rental_status == "possible" else 0.55,
            "rental_positive_signals": reason if rental_status == "possible" else "",
            "rental_negative_signals": "",
            "rental_decision_needed": "yes" if rental_status == "unclear" else "no",
            "rental_email_question": reason[:200] if rental_status == "unclear" else "",
            "activity_tags": "",
            "space_tags": "",
            "constraints_tags": "",
            "description": reason,
            "evidence_text": evidence[:500],
            "missing_formal_fields": ", ".join(missing),
            "email_questions": ", ".join(missing),
            "page_type": page_type,
            "source_reliability": reliability,
            "geo_status": "in_scope",
            "specific_rental_page_url": norm_text(rental_page),
            "observation_count": ent.get("observation_count", 1),
            "candidate_status": "to_contact" if rental_status == "possible" else "new",
            "_dataset": "candidate",
            "dedupe_key": f"{slug(name)}_{slug(city)}",
            "last_seen_at": datetime.now().isoformat()[:10],
            "ai_source_record_id": rec.get("venue_entity_id", ""),
            "ai_source_file": rec.get("_source_ai_file", ""),
            "ai_source_kind": source_kind,
        },
    }


def dedupe_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for f in features:
        p = f["properties"]
        key = p.get("dedupe_key") or p.get("candidate_id")
        score = p.get("fit_beyond_score", 0) + (20 if p.get("specific_rental_page_url") else 0) + (10 if p.get("contact") else 0)
        if key not in best or score > best[key]["_score"]:
            best[key] = {"_score": score, "feature": f}
    return [v["feature"] for v in best.values()]


def build(run_dir: Path, output_geojson: Path, output_funnel: Path, csv_dir: Path, date_tag: str) -> dict[str, Any]:
    entities, curated, obs_by_id, ent_by_id = build_indexes(run_dir)
    ai_records = load_ai_records(run_dir)
    ai_by_id = {r.get("venue_entity_id"): r for r in ai_records}

    features: list[dict[str, Any]] = []
    imported_source_ids: set[str] = set()
    invalid_categories = Counter()

    for rec in ai_records:
        category = norm_text(rec.get("page_category"))
        if category in NON_VENUE_CATEGORIES or rec.get("is_venue_page") is False:
            invalid_categories[category or "non_venue"] += 1
            continue
        parent = parent_context(rec, ent_by_id, obs_by_id)

        extracted_from_mi, _missing = dictish_missing(rec)
        fields = {**extracted_from_mi}
        fields.setdefault("venue_name", norm_text(rec.get("venue_name", "")))
        single = feature_from_fields(candidate_id=rec.get("venue_entity_id", ""), fields=fields, parent=parent, rec=rec, source_kind="single")
        if single:
            features.append(single)
            imported_source_ids.add(rec.get("venue_entity_id", ""))

        extracted = rec.get("extracted_venues") or []
        if isinstance(extracted, list):
            for idx, venue in enumerate(extracted):
                if not isinstance(venue, dict):
                    continue
                cid = f"{rec.get('venue_entity_id','')}_x{idx}_{h(json.dumps(venue, ensure_ascii=False, sort_keys=True))}"
                fx = feature_from_fields(candidate_id=cid, fields={str(k): v for k, v in venue.items()}, parent=parent, rec=rec, source_kind="extracted_from_listing")
                if fx:
                    features.append(fx)
                    imported_source_ids.add(rec.get("venue_entity_id", ""))

    features = dedupe_features(features)
    geojson = {"type": "FeatureCollection", "features": features}
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / f"import_queue_{date_tag}.csv"
    keys = sorted(set(k for f in features for k in f["properties"].keys()))
    with io.StringIO() as buf:
        writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for f in features:
            writer.writerow({k: norm_text(v) for k, v in f["properties"].items()})
        csv_path.write_text(buf.getvalue(), encoding="utf-8")

    # Funnel/debug over all resolved entities, not only imported records.
    items = []
    stage_counts = Counter()
    imported_feature_ids = {f["properties"].get("ai_source_record_id") for f in features}
    for ent in entities:
        eid = ent.get("venue_entity_id", "")
        rec = ai_by_id.get(eid, {})
        page_type = norm_text(rec.get("page_category") or ent.get("primary_page_type") or "unknown")
        geo_status = ent.get("geo_status", "unknown")
        reliability = ent.get("primary_source_reliability", "")
        source_url = first(rec.get("url"), ent.get("official_website_url"))
        if eid in imported_feature_ids:
            stage, reason = "L4_import_queue", "Importé dans la carte depuis extraction IA adaptative."
        elif page_type == "aggregator_listing" or "listing" in page_type and eid not in ai_by_id:
            stage, reason = "L0_aggregator", "Observation agrégateur/listing conservée pour lineage, pas une salle finale."
        elif geo_status in {"out_of_zone", "homonym"} or page_type == "out_of_region":
            stage, reason = "L2_filtered_geo", first(rec.get("classification_reason"), "Hors zone IDF / homonyme.")
        elif reliability in {"S0", "S1", "S2"} and eid not in ai_by_id:
            stage, reason = "L2_filtered_reliability", "Source trop faible avant extraction IA."
        elif rec and (rec.get("is_venue_page") is False or page_type in NON_VENUE_CATEGORIES):
            stage, reason = "L3_not_venue", first(rec.get("classification_reason"), f"Classé {page_type} par l'IA.")
        elif rec and rec.get("is_venue_page") is None:
            stage, reason = "L3_not_venue", first(rec.get("classification_reason"), "Extraction incertaine / scrape incomplet.")
        else:
            stage, reason = "L3_valid_but_missing", "Salle potentielle non importée : coordonnées ou champs critiques insuffisants / normalisation à revoir."
        stage_counts[stage] += 1
        items.append({
            "venue_entity_id": eid,
            "name": first(rec.get("venue_name") if rec else "", ent.get("canonical_name")),
            "city": ent.get("canonical_city", ""),
            "stage": stage,
            "stop_reason": reason,
            "page_type": page_type,
            "source_reliability": reliability,
            "geo_status": geo_status,
            "rental_possible": "possible" if (rec.get("is_rental_page") or page_type in RENTAL_POSITIVE_CATEGORIES) else "unclear",
            "source_url": source_url,
            "has_ai_retry_result": bool(rec),
            "ai_source_file": rec.get("_source_ai_file", "") if rec else "",
        })
    output_funnel.parent.mkdir(parents=True, exist_ok=True)
    output_funnel.write_text(json.dumps({"items": items, "stage_counts": dict(stage_counts), "generated_at": datetime.now().isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "generated_at": datetime.now().isoformat(),
        "ai_records": len(ai_records),
        "features": len(features),
        "with_coords": sum(1 for f in features if f["geometry"]["coordinates"] != [0, 0]),
        "without_coords": sum(1 for f in features if f["geometry"]["coordinates"] == [0, 0]),
        "rental_possible": sum(1 for f in features if f["properties"]["rental_possible_status"] == "possible"),
        "rental_unclear": sum(1 for f in features if f["properties"]["rental_possible_status"] == "unclear"),
        "has_contact": sum(1 for f in features if f["properties"]["contact"]),
        "has_price": sum(1 for f in features if f["properties"]["price_text"]),
        "has_capacity": sum(1 for f in features if f["properties"]["capacity_text"]),
        "has_rental_page": sum(1 for f in features if f["properties"]["specific_rental_page_url"]),
        "source_kind_distribution": dict(Counter(f["properties"]["ai_source_kind"] for f in features)),
        "page_type_distribution": dict(Counter(f["properties"]["page_type"] for f in features).most_common()),
        "stage_counts": dict(stage_counts),
        "invalid_categories_skipped": dict(invalid_categories.most_common()),
        "csv_path": str(csv_path),
        "geojson_path": str(output_geojson),
        "funnel_path": str(output_funnel),
    }
    (csv_dir / f"report_{date_tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="data/discovery_runs/20260620_multisource_lineage_enriched")
    ap.add_argument("--output", default="public/import_queue.geojson")
    ap.add_argument("--funnel-output", default="public/funnel_debug.json")
    ap.add_argument("--csv-dir", default="data/import_queue")
    ap.add_argument("--date-tag", default=datetime.now().strftime("%Y%m%d") + "_adaptive_ai")
    args = ap.parse_args()
    report = build(Path(args.run_dir), Path(args.output), Path(args.funnel_output), Path(args.csv_dir), args.date_tag)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
