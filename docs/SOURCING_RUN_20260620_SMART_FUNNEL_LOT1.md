# Smart sourcing funnel — Lot 1 lineage / observations

## Date

2026-06-20

## Objectif du lot

Transformer le sourcing amont en entonnoir réexécutable et auditable, sans encore prétendre résoudre parfaitement les salles finales.

Principe implémenté :

```text
provider outputs / legacy source_records
  -> source_observations communes
  -> content_cache + raw_payload hashes
  -> field_evidence minimal
  -> discovery_runs/<run_id>/ non destructif
```

## Nouveaux fichiers

```text
scripts/sourcing/discover_with_tavily.py
scripts/sourcing/build_discovery_run.py
scripts/sourcing/validate_discovery_run.py

data/schema/source_observation.schema.json
data/schema/field_evidence.schema.json

config/tavily_south_banlieue_prompts_fr.json
config/tavily_south_banlieue_prompts.json

docs/SMART_SOURCING_FUNNEL_AND_LINEAGE.md
```

## Tavily prompt discovery

Commande :

```bash
python3 scripts/sourcing/discover_with_tavily.py \
  --prompts config/tavily_south_banlieue_prompts_fr.json \
  --output data/source_records/tavily_south_banlieue_prompt_discovery_fr_20260620.json \
  --report data/source_records/tavily_south_banlieue_prompt_discovery_fr_20260620.report.json \
  --run-id 20260620_tavily_prompt_south_fr \
  --max-results 8 \
  --include-raw-content
```

Résultat :

```json
{
  "provider": "tavily",
  "prompts": 5,
  "raw_results": 40,
  "output_records": 40,
  "duplicate_urls_detected": 5,
  "duplicate_urls_removed": 0,
  "dedupe_urls": false,
  "errors": []
}
```

Important : les doublons URL sont conservés par défaut pour ne pas perdre le lineage par prompt/rank. Utiliser `--dedupe-urls` seulement si on veut explicitement l'ancien comportement.

## Discovery run enrichi

Commande :

```bash
python3 scripts/sourcing/build_discovery_run.py \
  data/source_records/tavily_south_banlieue_prompt_discovery_fr_20260620.json \
  data/source_records/rental_qualified_beyond_idf_20260620.json \
  --run-id 20260620_multisource_lineage_enriched
```

Résultat :

```json
{
  "observations": 1082,
  "field_evidence": 5022,
  "malformed": 0,
  "observations_by_provider": {
    "tavily": 40,
    "legacy_source_records": 1042
  },
  "observations_with_url": 1082,
  "observations_with_query": 250,
  "observations_with_content_hash": 1082,
  "field_evidence_by_field": {
    "website": 872,
    "specific_rental_page": 766,
    "rental_possible": 1042,
    "address": 615,
    "contact": 733,
    "price": 449,
    "capacity": 545
  },
  "duplicate_url_groups_preserved": 117,
  "duplicate_observations_preserved": 323
}
```

Artefacts :

```text
data/discovery_runs/20260620_multisource_lineage_enriched/observations.json
data/discovery_runs/20260620_multisource_lineage_enriched/field_evidence.json
data/discovery_runs/20260620_multisource_lineage_enriched/report.json
data/discovery_runs/20260620_multisource_lineage_enriched/schema_validation_report.json
data/discovery_runs/20260620_multisource_lineage_enriched/provider_raw/
data/discovery_runs/20260620_multisource_lineage_enriched/content_cache/
```

## Validation

Commande :

```bash
python3 scripts/sourcing/validate_discovery_run.py \
  data/discovery_runs/20260620_multisource_lineage_enriched
```

Résultat :

```json
{
  "valid": true,
  "errors_count": 0,
  "observations": 1082,
  "field_evidence": 5022,
  "with_specific_rental_page": 766,
  "with_content_hash": 1082
}
```

Non-destruction vérifiée :

```text
protected_diff_exit:0
```

Fichiers protégés inchangés :

```text
data/salles_small_idf.csv
public/salles_small_idf.geojson
data/salles_all_idf.csv
public/salles_all_idf.geojson
public/import_queue.geojson
```

## Ce qui est volontairement non résolu dans ce lot

Ce lot ne fait pas encore :

```text
classification page/source robuste
entity resolution en venue_entities
Google Places live
Google Maps live
Google Search live
LLM structured extraction avec citations
curated UX par entité
batch email
```

Il crée la fondation commune où ces providers et extracteurs peuvent maintenant se brancher proprement.

## Leçons du POC Tavily

- Tavily `/search` accepte des prompts naturels courts, pas des prompts ChatGPT longs ; limite constatée ~400 caractères.
- Les prompts français sont meilleurs que les prompts anglais pour ce sourcing local.
- Tavily ramène encore des agrégateurs / hors-zone ; c'est normal à ce stade : ils doivent être observés puis filtrés/classés, pas promus directement en salles.
- Les doublons URL par prompt sont utiles pour comprendre quel angle de recherche trouve quelle page.

## Prochain lot recommandé

```text
Lot 2 — source/page classifier + geo guard
  - classer official_rental_page / municipal / aggregator / directory / social / irrelevant
  - rejeter homonymes et hors-zone : Châtillon-en-Vendelais, USA, Royan, Loiret, etc.
  - produire page_type + source_reliability S0-S5

Lot 3 — entity resolver minimal
  - regrouper observations vers venue_entities
  - séparer official_website_url et specific_rental_page_url
  - garder tous les observation_ids

Lot 4 — LLM structured extraction avec citations
  - price/capacity/contact/rental/address structurés
  - evidence_quote obligatoire
  - confidence par champ
```
