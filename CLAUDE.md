# CLAUDE.md — salles-idf-sig

## Project Context

Static map site displaying small venue rooms (≤20 people, budget-friendly) in Île-de-France. Serves as a prospecting tool for finding affordable meeting/event spaces across Paris and surrounding departments.

## Stack

- **Data**: CSV source (`data/salles_small_idf.csv`) → GeoJSON (`public/salles_small_idf.geojson`)
- **Frontend**: Vanilla HTML/CSS/JS, Leaflet 1.9.4, OpenStreetMap tiles
- **Build**: Python script (`scripts/build_small_dataset.py`) for geocoding + CSV→GeoJSON
- **Deploy**: Scaleway Object Storage + CDN (static hosting)
- **CI/CD**: GitHub Actions

## Conventions

- French locale for all UI text (project is for French market)
- Department codes as filter keys: 75, 92, 93, 94, 77, 78, 91, 95
- `fit_score` (0–100) as primary ranking metric (higher = better fit)
- `price_score` (0–100) as affordability indicator (higher = cheaper)
- No framework — keep it static, fast, and simple for MVP
- Always preserve existing data files; scripts are additive

## 6 Pillars

1. **Data integrity**: Never modify CSV/GeoJSON by hand; use scripts
2. **Mobile-first**: Responsive map UI, touch-friendly filters
3. **Accessibility**: Semantic HTML, ARIA labels, color-blind-safe markers
4. **Performance**: No build step, no framework, CDN-hosted Leaflet only
5. **Deploy automation**: Push to staging → auto-deploy to Scaleway
6. **Separation of concerns**: Data layer (scripts/) vs presentation (public/)

## Branch Model

| Branch | Purpose | Deploy |
|--------|---------|--------|
| `dev` | Feature work, vibe coding | None |
| `staging` | Integration & QA | Auto → Scaleway staging bucket + CDN |
| `master` | Production | Manual merge from staging → Scaleway prod |

- Never push directly to `master`
- Merge `staging → master` is Anthony's decision (requires approval)

## Key Files

- `public/index.html` — Main map page (Leaflet + GeoJSON)
- `public/salles_small_idf.geojson` — Venue data for the map
- `data/salles_small_idf.csv` — Source of truth for venue data
- `scripts/build_small_dataset.py` — Geocode + generate GeoJSON + HTML
- `.github/workflows/pr-checks.yml` — Lint & validate on PRs
- `.github/workflows/deploy-staging.yml` — Auto-deploy staging on push to staging
- `.github/workflows/deploy-prod.yml` — Deploy prod on merge to master (with approval gate)

## Environment Variables (CI)

```
SCALEWAY_ACCESS_KEY    — Scaleway API access key
SCALEWAY_SECRET_KEY    — Scaleway API secret key
SCALEWAY_BUCKET_STAGING — Staging bucket name (e.g., salles-idf-staging)
SCALEWAY_BUCKET_PROD    — Prod bucket name (e.g., salles-idf-prod)
SCALEWAY_REGION         — Scaleway region (e.g., fr-par)
```

## Data Schema

See `data/salles_small_idf.csv` headers:
`id, name, city, department, address, lat, lon, geocode_score, geocode_label, category, capacity_text, capacity_max_detected, price_text, price_score, website, contact, source_url, pros, cons, confidence, fit_score, last_checked`