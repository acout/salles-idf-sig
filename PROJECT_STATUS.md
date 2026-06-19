# PROJECT_STATUS.md — salles-idf-sig

## Overview

| Item | Status |
|------|--------|
| Project | salles-idf-sig |
| Type | Static prospecting CRM + map (Leaflet + GeoJSON + localStorage) |
| Repo | `acout/salles-idf-sig` on GitHub |
| Last updated | 2026-06-19 |

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
- [x] Status tracking per venue: à qualifier, shortlist, contactée, candidature envoyée, OK, refus, utilisée
- [x] Per-venue notes/comments stored in `localStorage`
- [x] Next action + date for relance workflow
- [x] Event history per venue to remember which rooms have served before
- [x] Favorites ⭐
- [x] Export/import JSON backup of the local follow-up database

## Recommended Next Steps

- [ ] Add a real backend/sync layer if multiple devices/users need the same follow-up state
- [ ] Add “last contacted at” and “contact channel” fields
- [ ] Add canned call/email script templates per venue type
- [ ] Add quality score after event: accessibility, accueil, bruit, prix final, would reuse?
- [ ] Add CSV export of shortlist + contacted venues
- [ ] Add data quality queue for bad geocodes / duplicates / source confidence
