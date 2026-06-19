# PROJECT_STATUS.md — salles-idf-sig

## Overview

| Item | Status |
|------|--------|
| Project | salles-idf-sig |
| Type | Static map site (Leaflet + GeoJSON) |
| Repo | `acout/salles-idf-sig` on GitHub |
| Last updated | 2026-06-19 |

## Deployments

| Environment | Branch | URL | Method |
|-------------|--------|-----|--------|
| Staging | `staging` | `https://salles-idf-staging.s3-website.fr-par.scw.cloud` | GitHub Actions → Scaleway Object Storage |
| Production | `master` | `https://salles-idf-prod.s3-website.fr-par.scw.cloud` (TBD) | Manual merge from staging → Scaleway |

## Branch Model

| Branch | Purpose | Deploy | Protection |
|--------|---------|--------|------------|
| `dev` | Feature development | None | None |
| `staging` | Integration testing | Auto-deploy to Scaleway staging | Require PR review |
| `master` | Production release | Deploy on merge (manual trigger) | Protected, require approval |

## Data Status

- **Venues**: 25 small rooms (≤20 people) across Île-de-France
- **Departments covered**: 75, 92, 93, 94, 78, 91, 95
- **Geocoding**: All venues geocoded via BAN (API Adresse)
- **Last data refresh**: 2026-06-19

## Next Steps

- [ ] Increase venue coverage to 80–120 (add grande couronne departments 77, 91)
- [ ] Add capacity min/max filter slider
- [ ] Add category filter (coworking, municipal, associations)
- [ ] Add CRM status tracking (to_check, shortlist, contacted)
- [ ] Add CSV/Markdown export for shortlist