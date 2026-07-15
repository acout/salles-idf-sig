# Smart sourcing funnel & lineage — Beyond venue sourcing

## Intent

Build the venue sourcing pipeline as an additive, auditable funnel:

```text
multi-source discovery
  -> raw source observations
  -> source/page classification
  -> page/content extraction
  -> venue entity resolution
  -> field-level extraction with evidence
  -> qualification/scoring
  -> import queue / SIG / CRM
  -> email readiness
```

The canonical venue dataset must not be overwritten by discovery runs. Each run adds observations, preserves lineage, and produces reviewable candidates.

## Principle: sources are observations, not venues

A Google Places result, a Tavily result, an aggregator listing, an official page, a mairie page, an OSM object, and a Maps URL are all **observations** about a possible venue.

They should feed a common observation table/schema, then be resolved into canonical venue entities later.

```text
source_observations[]  --many-to-one-->  venue_entities[]
                                      ->  field_evidence[]
                                      ->  import_queue[]
```

## Funnel levels

### L0 — Discovery providers

Providers are pluggable and additive.

| Provider | Role | Output type | Trust by default |
|---|---|---|---|
| Tavily Search | AI-native prompt search for relevant pages | pages/snippets/raw content | medium |
| Google Search / Serp API | broad SERP discovery and official-page lookup | pages/snippets | medium |
| Google Places | real-world business/place discovery | place entities | high for existence/address/contact, low for rental metadata |
| Google Maps URL / Maps scrape if allowed | discovery and place corroboration | place/map references | medium |
| OSM / Overpass | geospatial baseline for community centres, dojos, studios, arts venues | map objects | medium-high for existence/coords |
| Institutional/open data | mairie, MJC, centres sociaux, public facility lists | pages/datasets | high |
| Aggregators | discovery of venues and market vocabulary | listing pages | low-medium, never canonical alone |
| Manual/user seed | user-known venues | seed observations | high but still needs verification |

### L1 — Raw source observation

Every provider writes to the same observation schema. Nothing is discarded at this layer except malformed rows.

Required lineage fields:

```json
{
  "observation_id": "obs_<hash>",
  "run_id": "20260620_tavily_prompt_south_fr",
  "provider": "tavily|google_search|google_places|osm|institutional|aggregator|manual",
  "provider_query_id": "fr_mairies_associations_salles",
  "provider_query_text": "Trouver pages mairie...",
  "provider_rank": 3,
  "provider_score": 0.82,
  "discovered_at": "2026-06-20T...",

  "source_url": "https://...",
  "source_domain": "ville-cachan.fr",
  "source_title": "Location de salle - Ville de Cachan",
  "source_snippet": "...",
  "source_raw_content_path": "data/source_cache/...txt",

  "place_id": null,
  "osm_id": null,
  "maps_url": null,

  "candidate_name_hint": "...",
  "candidate_address_hint": "...",
  "candidate_city_hint": "...",
  "candidate_lat_hint": null,
  "candidate_lon_hint": null
}
```

### L2 — Source/page classification

Classify the observation before extracting venue facts.

```json
{
  "observation_id": "...",
  "page_type": "official_venue_page|official_rental_page|municipal_facility_page|association_page|google_place|osm_object|aggregator_listing|aggregator_search_page|directory|social|course_only|irrelevant|unknown",
  "source_reliability": "S0|S1|S2|S3|S4|S5",
  "classification_method": "rules|llm|provider|manual",
  "classification_evidence": "...",
  "classification_confidence": 0.84
}
```

Source reliability scale:

```text
S5 = user-confirmed / email response / manual validation
S4 = official venue or institution page
S3 = mairie / association / public institutional source
S2 = dedicated aggregator listing
S1 = generic directory/search result/social snippet
S0 = noisy / irrelevant / untrusted
```

### L3 — Content extraction

Fetch/extract content with a traceable method.

Possible methods:

```text
Tavily include_raw_content
Tavily extract
requests + trafilatura/readability
BeautifulSoup structured metadata
JSON-LD / schema.org
PDF parser
Playwright fallback
Google Places details
OSM tags
```

Each extracted content artifact should be stored with path/hash:

```json
{
  "content_id": "content_<hash>",
  "observation_id": "obs_<hash>",
  "url": "https://...",
  "content_method": "tavily_raw|tavily_extract|html_readability|jsonld|pdf|places_details|osm",
  "content_sha256": "...",
  "content_path": "data/source_cache/<run>/<hash>.md",
  "extracted_at": "...",
  "http_status": 200,
  "content_language": "fr",
  "content_chars": 12432
}
```

### L4 — Venue entity resolution

Observations are grouped into venue entities. An entity can have many sources.

```json
{
  "venue_entity_id": "venue_<hash>",
  "canonical_name": "Maison des Associations de Cachan",
  "canonical_address": "...",
  "canonical_city": "Cachan",
  "canonical_department": "94",
  "canonical_lat": 48.79,
  "canonical_lon": 2.33,
  "entity_status": "candidate|merged|rejected|confirmed",
  "source_observation_ids": ["obs_...", "obs_..."],
  "primary_source_observation_id": "obs_...",
  "official_website_url": "https://...",
  "specific_rental_page_url": "https://...",
  "google_place_id": "...",
  "osm_id": "...",
  "created_from_run_id": "...",
  "last_seen_run_id": "..."
}
```

Resolution signals:

```text
same Google Place ID
same OSM ID
same normalized official domain
same phone/email
same BAN-normalized address
geo distance < threshold
name similarity
LLM/manual arbiter for ambiguous merges
```

### L5 — Field-level evidence extraction

Never store only `price_text` or `capacity_text` without evidence. Each critical fact has lineage.

```json
{
  "field_evidence_id": "fe_<hash>",
  "venue_entity_id": "venue_<hash>",
  "observation_id": "obs_<hash>",
  "content_id": "content_<hash>",
  "field_name": "price|capacity|contact|address|rental_possible|surface|availability|conditions",
  "value_raw": "35€/h ou 180€/jour",
  "value_structured": {
    "hourly_eur": 35,
    "daily_eur": 180
  },
  "evidence_quote": "La salle est proposée à la location au tarif de 35€/h...",
  "evidence_url": "https://...#section",
  "extraction_method": "regex|llm_structured|jsonld|places_details|osm_tags|manual",
  "confidence": 0.78,
  "extracted_at": "..."
}
```

Canonical venue fields are then selected from evidence candidates by priority:

```text
manual/user-confirmed > official rental page > official venue page > mairie/institution > Google Places/OSM > aggregator > directory/snippet
```

### L6 — Qualification & scoring

Separate scores, do not collapse everything into one opaque score.

```json
{
  "venue_entity_id": "venue_<hash>",
  "fit_beyond_score": 82,
  "rental_probability_score": 76,
  "data_completeness_score": 61,
  "source_reliability_score": 88,
  "geo_confidence_score": 94,
  "email_readiness_score": 52,
  "priority_score": 74,
  "curation_status": "curated_ok|needs_review|source_only|likely_reject",
  "score_reasons": ["official rental page", "contact present", "price missing", "capacity unclear"]
}
```

### L7 — Import queue / SIG / CRM

The UI should show the entity and its lineage:

```text
Primary venue card
  - canonical source
  - official website
  - specific rental page if any
  - all source observations
  - field evidence for price/capacity/contact/rental
  - confidence and missing fields
  - email readiness
```

Recommended UX layers:

```text
Curated OK
Needs review
Source-only / aggregator to exploit
Likely reject
```

### L8 — Email readiness

Email generation should be downstream of evidence quality, not just contact presence.

```json
{
  "venue_entity_id": "venue_<hash>",
  "email_ready": false,
  "email_mode": "ask_missing_info|clarify_rental|apply|not_relevant|missing_contact",
  "recipient_evidence_id": "fe_<hash>",
  "personalization_facts": [
    {"fact": "studio de yoga", "evidence_id": "fe_..."},
    {"fact": "location mentionnée", "evidence_id": "fe_..."}
  ],
  "questions_to_ask": ["capacité mouvement", "tarif horaire", "créneaux soir/week-end"]
}
```

## Provider-specific notes

### Tavily

Use prompt-style short French queries (<400 chars for `/search`). Good for semantic web-page discovery and raw content ingestion. Not enough alone for curated truth.

### Google Search / Serp API

Use for broad page discovery and official-site lookup. It is page-oriented, not place-oriented.

### Google Places

Use for real-world place existence, coordinates, phone, website, opening hours, categories, reviews count. Do not treat it as proof of room rental.

### Google Maps URL

Keep as lineage/corroboration. Prefer Place ID when available. Avoid brittle scraping unless legally/technically acceptable.

### OSM / Overpass

Use for geospatial exhaustiveness and coordinates. It will miss commercial rental detail but catches facilities search engines miss.

### Aggregators

Aggregators should primarily create child observations and discovery leads. They should not become high-confidence venue facts unless corroborated.

## Non-destructive storage layout

```text
data/discovery_runs/<run_id>/
  observations.json
  provider_raw/
  content_cache/
  report.json

data/entities/
  venue_entities.json
  field_evidence.json
  entity_resolution_report.json

data/import_queue/
  import_queue_<run_id>.csv
  import_queue_<run_id>.geojson
  report_<run_id>.json

public/import_queue.geojson  # latest publication copy only
```

## Acceptance criteria for next implementation lot

- [ ] New discovery providers write common observation schema.
- [ ] Every observation preserves provider, query/prompt, rank, URL, and timestamp.
- [ ] Specific rental page URL is separate from general website URL.
- [ ] Field-level evidence stores quote, source URL, method, confidence.
- [ ] Entity resolution keeps all source observation IDs.
- [ ] Import queue is generated from entities/evidence, not raw source rows alone.
- [ ] Existing canonical CSV/GeoJSON are not overwritten.
- [ ] Run report includes counts per provider, page type, source reliability, field completeness, geocoded count, rejection reasons.
