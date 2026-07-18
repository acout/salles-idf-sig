# CLAUDE.md — salles-idf-sig

## Project Context

Static map and authenticated collaboration cockpit for finding, qualifying and calling affordable venue rooms in Île-de-France.

## Stack

- **Data**: source datasets → public catalogue (`public/salles_catalog_public.geojson`) + private sourcing import
- **Frontend**: Vanilla HTML/CSS/JS, Leaflet 1.9.4, OpenStreetMap tiles
- **Backend**: Supabase Auth/Postgres/RLS/RPC/Realtime for shared work
- **Build**: Python release, import and validation scripts
- **Deploy**: GitHub Pages for staging; production remains an explicit Anthony decision
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
5. **Deploy automation**: Push to staging → auto-deploy to GitHub Pages
6. **Separation of concerns**: Data layer (scripts/) vs presentation (public/)

## Branch Model

| Branch | Purpose | Deploy |
|--------|---------|--------|
| `dev` | Feature work, vibe coding | None |
| `staging` | Integration & QA | Auto → GitHub Pages |
| `master` | Production | Manual merge from staging; Anthony approval required |

- Never push directly to `master`
- Merge `staging → master` is Anthony's decision (requires approval)

## Key Files

- `public/index.html` — Main map page (Leaflet + GeoJSON)
- `public/salles_catalog_public.geojson` — 275 public venue records
- `public/js/sourcing-inbox.js` — Shared sourcing workflow
- `scripts/build_public_private_release.py` — Deterministic public/private release
- `scripts/admin_import_sourcing_candidates.py` — Additive import of the 253 approved candidates
- `supabase/migrations/20260716_sourcing_inbox.sql` — Sourcing data contract and RPCs
- `.github/workflows/pr-checks.yml` — Lint & validate on PRs
- `.github/workflows/deploy-staging.yml` — Auto-deploy staging on push to staging
- `.github/workflows/deploy-prod.yml` — Deploy prod on merge to master (with approval gate)

## Environment Variables (CI)

```
SCALEWAY_ACCESS_KEY    — Scaleway API access key
SCALEWAY_SECRET_KEY    — Scaleway API secret key
SCALEWAY_BUCKET_PROD    — Prod bucket name (e.g., salles-idf-prod)
SCALEWAY_REGION         — Production Scaleway region (e.g., fr-par)
APP_MODE                — `read_only` or `shared`
APP_RELEASE             — Release identifier injected into runtime config
SUPABASE_URL            — public project URL
SUPABASE_ANON_KEY       — public browser key
```

`SUPABASE_PRIVATE_BUCKET` is a local/admin setting for bootstrap scripts; it is not injected by the current CI workflows.

## Data Schema

See `public/dataset-manifest.json` for the public release contract and `supabase/migrations/20260716_sourcing_inbox.sql` for the private candidate, observation, evidence and event schema.
