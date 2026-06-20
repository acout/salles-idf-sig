# PROJECT_STATUS.md — salles-idf-sig

## Overview

| Item | Status |
|------|--------|
| Project | salles-idf-sig |
| Type | Static prospecting CRM + map (Leaflet + GeoJSON + localStorage) |
| Repo | `acout/salles-idf-sig` on GitHub |
| Last updated | 2026-06-20 |

## Deployments

| Environment | Branch | URL | Method |
|-------------|--------|-----|--------|
| Local | `dev` | `http://127.0.0.1:8123/` | Python static server |
| Staging | `staging` | `https://salles-idf-staging.s3-website.fr-par.scw.cloud` | GitHub Actions → Scaleway Object Storage |
| Production | `master` | `https://salles-idf-prod.s3-website.fr-par.scw.cloud` (TBD) | Manual merge from staging → Scaleway |

## Branch Model

| Branch | Purpose | Deploy | Protection |
|--------|---------|--------|------------|
| `dev` | Feature development | None | None |
| `staging` | Integration testing | Auto-deploy to Scaleway staging | Require PR review |
| `master` | Production release | Deploy on merge (manual trigger) | Protected, require approval |

## Data Status

- **Venues**: 275 collected venues, 143 visible by default after IDF bbox + capacity ≤20 filters
- **Departments covered**: 75, 77, 78, 91, 92, 93, 94, 95
- **Geocoding**: GeoJSON coordinates via BAN + scraped coordinates; frontend excludes out-of-IDF false geocodes
- **Last data refresh**: 2026-06-19

## Product Status

Implemented:

- [x] Map view with jitter for overlapping markers
- [x] List/table view for operational prospecting
- [x] Pipeline/Kanban view by prospecting status
- [x] Quick status progression buttons in pipeline
- [x] Copyable call script and candidature email templates per venue
- [x] Data quality filter and badges: contact, price, capacity, duplicate, geocode
- [x] Local enrichment overrides for contact, price, capacity, address and source reliability
- [x] Corrected local values displayed across detail, cards, list, pipeline, scripts and export/import
- [x] Status tracking per venue: à qualifier, shortlist, contactée, candidature envoyée, OK, refus, utilisée
- [x] Per-venue notes/comments stored in `localStorage`
- [x] Next action + date for relance workflow
- [x] Event history per venue to remember which rooms have served before
- [x] Favorites ⭐
- [x] Export/import JSON backup of the local follow-up database
- [x] Sourcing foundation: source/candidate/venue/user-overlay/suggested-update schemas
- [x] Beyond-compatible venue taxonomy and scoring config
- [x] Non-destructive merge policy to protect user CRM/enrichment data
- [x] Demo import queue pipeline (`scripts/sourcing/build_import_queue.py --demo`)
- [x] Autonomous Beyond sourcing run 2026-06-19: 210 raw source records, 193 deduped import candidates
- [x] Import queue generated without modifying canonical venue data or user overlay
- [x] Banlieue sud targeted run 2026-06-20: +149 raw records around Cachan/Châtillon corridor, 334 total import candidates, 83 mapped candidates in 92/94
- [x] Formal enrichment run 2026-06-20: aggregator detection/expansion, scrape status for every final item, 834 import candidates, 344 mapped, 604 with contact, 363 with price, 433 with capacity
- [x] Rental qualification run 2026-06-20: `possible/unclear/unlikely` classification, Fitness/gym/class-only detection, 337 possible / 469 unclear / 28 unlikely in final queue
- [x] Repeatable additive source-record merge script (`scripts/sourcing/merge_source_records.py`)
- [x] Full re-executable Beyond import pipeline runner (`scripts/sourcing/run_beyond_pipeline.py`)
- [x] Smart sourcing funnel Lot 1 2026-06-20: common `source_observations` + `field_evidence` lineage, Tavily prompt-search provider, run-scoped `data/discovery_runs/`, 1082 observations / 5022 field evidences validated without touching canonical data
- [x] Smart sourcing funnel Lot 2 2026-06-20: source/page classifier + strict geo guard — `classify_observations.py` classifies 1082 observations into page_type (aggregator 629, official_rental 155, official_venue 219, municipal 45, social 25, course_only 3, pdf 2, unknown 4) + source_reliability (S1 657, S3 264, S4 155, S2 5, S0 1) + geo_status (in_scope 1021, out_of_zone 38, geo_unknown 13, homonym 10). In-scope high-quality: 383
- [x] Smart sourcing funnel Lot 3 2026-06-20: entity resolution — `resolve_entities.py` groups 1082 observations into 1075 entities (466 venue entities + 609 aggregator observations), 7 multi-observation merges, 379 curated in-scope high-quality venues; official_website_url and specific_rental_page_url separated
- [x] Smart sourcing funnel Lot 4 2026-06-20: AI structured extraction on 379 curated entities — 165 identified as actual venues, 110 rental_yes, 35 rental_no, 234 rental_unclear; 49 with address, 25 with phone, 14 with email, 79 with rental page; price/capacity evidence lower due to aggregator content; extraction with evidence quotes and confidence scores
- [x] Funnel pipeline → app integration: convert_to_import_queue.py produces 165 curated in-scope entities as import_queue.geojson; app JS updated with Source & lineage detail panel (page_type, source_reliability, geo_status, observation_count, specific_rental_page_url, evidence_text); CSS badges for src-type, reliability (S1-S4), geo-status

## Recommended Next Steps

- [ ] Smart funnel Lot 2: source/page classifier + strict geo guard before promotion (`official_rental_page`, `municipal`, `aggregator`, `irrelevant`, reliability S0-S5)
- [ ] Smart funnel Lot 3: minimal venue entity resolver preserving all observation IDs and separating website vs specific rental page
- [ ] Smart funnel Lot 4: LLM structured extraction with citations for price/capacity/contact/rental/address
- [ ] Add a real backend/sync layer if multiple devices/users need the same follow-up state
- [ ] Add “last contacted at” and “contact channel” fields
- [ ] Add canned call/email script templates per venue type
- [ ] Add quality score after event: accessibility, accueil, bruit, prix final, would reuse?
- [ ] Add CSV export of shortlist + contacted venues
- [ ] Add data quality queue for bad geocodes / duplicates / source confidence
