# Sourcing run — 2026-06-20 — Formal enrichment + aggregator handling

## Problème corrigé

Anthony a signalé que beaucoup de points cartographiés étaient en fait des agrégateurs/listings, pas des salles directement actionnables. Le besoin produit :

1. Ne pas faire passer un agrégateur pour une salle.
2. Quand possible, extraire des salles/liens enfants depuis l'agrégateur.
3. Scraper chaque item final pour récupérer les infos formelles : adresse précise, contact, prix, capacité.
4. Afficher ce qui manque encore pour savoir quoi demander par email.

## Étapes exécutées

### 1. Audit queue initiale

Sur la queue précédente :

```json
{
  "items": 334,
  "geocoded": 83,
  "suspected_aggregators": 123,
  "missing": {
    "address": 251,
    "contact": 334,
    "price_text": 334,
    "capacity_text": 334
  }
}
```

Top domaines problématiques : PagesJaunes, ABC Salles, Spectable, Facebook, 1001Salles, Privateaser, Peerspace, Ville-data, etc.

### 2. Scraping formel + expansion agrégateurs

Script ajouté :

```text
scripts/sourcing/enrich_formal_fields.py
```

Il fait :

- fetch HTML direct avec timeout court ;
- extraction emails / téléphones ;
- extraction prix ;
- extraction capacité / surface ;
- extraction adresse ;
- classification `is_aggregator=yes/no` ;
- domaine agrégateur `aggregator_domain` ;
- pour agrégateurs : extraction de liens enfants quand possible ;
- calcul `missing_formal_fields` ;
- génération `email_questions`.

Premier passage :

```json
{
  "input_records": 359,
  "scraped_records": 250,
  "fetch_failed_records": 109,
  "aggregator_records": 201,
  "child_links_added": 683,
  "combined_output_records": 1042,
  "with_address": 214,
  "with_contact": 222,
  "with_price": 122,
  "with_capacity": 164
}
```

### 3. Scraping formel sur chaque item final

Pour respecter “checker chaque item dans la liste”, une deuxième passe a été lancée sur les 1042 records étendus, sans ré-expansion :

```json
{
  "input_records": 1042,
  "scraped_records": 818,
  "fetch_failed_records": 224,
  "with_address": 615,
  "with_contact": 733,
  "with_price": 449,
  "with_capacity": 545,
  "formal_complete_raw_records": 323
}
```

### 4. Géocodage BAN des adresses extraites

Script ajouté :

```text
scripts/sourcing/geocode_source_records.py
```

Résultat :

```json
{
  "input_records": 1042,
  "with_coordinates": 428,
  "statuses": {
    "missing_address": 427,
    "geocoded_ban": 344,
    "outside_idf": 120,
    "not_found": 29,
    "low_score": 36,
    "already_had_coordinates": 84
  }
}
```

### 5. Import queue finale

Après normalisation / scoring / déduplication / matching existant :

```json
{
  "input_records": 1042,
  "deduped_candidates": 835,
  "existing_matches": 1,
  "import_queue": 834,
  "mapped_import_queue": 344,
  "unmapped_import_queue": 490,
  "aggregator_items": 538,
  "scraped_items": 677,
  "scrape_failed_items": 157,
  "formal_complete_items": 248,
  "with_contact": 604,
  "with_price": 363,
  "with_capacity": 433
}
```

Mapped candidates par département :

```json
{
  "75": 15,
  "77": 18,
  "78": 13,
  "91": 21,
  "92": 146,
  "93": 25,
  "94": 84,
  "95": 22
}
```

## Nouveaux fichiers

```text
data/source_records/formal_enriched_beyond_idf_20260620.json
data/source_records/formal_enriched_beyond_idf_20260620.report.json
data/source_records/formal_enriched_geocoded_beyond_idf_20260620.json
data/source_records/formal_enriched_geocoded_beyond_idf_20260620.report.json
data/source_records/formal_enriched_checked_all_beyond_idf_20260620.json
data/source_records/formal_enriched_checked_all_beyond_idf_20260620.report.json
data/source_records/formal_enriched_checked_all_geocoded_beyond_idf_20260620.json
data/source_records/formal_enriched_checked_all_geocoded_beyond_idf_20260620.report.json
data/candidates/candidates_20260620_formal_checked.json
data/candidates/candidates_20260620_formal_checked.csv
data/import_queue/duplicates_20260620_formal_checked.json
data/import_queue/report_20260620_formal_checked.json
data/import_queue/email_questions_20260620_formal_checked.csv
data/import_queue/email_questions_20260620_formal_checked.summary.json
```

## UI ajoutée

L'app affiche maintenant :

- badge orange `Agrégateur` ;
- filtre qualité `Agrégateur / listing` ;
- filtre qualité `Infos formelles à demander` ;
- filtre qualité `Scraping échoué` ;
- dans la fiche : section `Scraping formel` avec statut, domaine agrégateur, complétude, liens extraits ;
- dans la fiche : encart `À demander par email` ;
- le template email ajoute automatiquement les questions restantes.

## Lecture produit

- Un agrégateur reste visible comme donnée SIG, mais il n'est plus confondu avec une salle.
- Quand l'agrégateur a permis d'extraire des liens enfants, ces liens deviennent des candidats séparés.
- Chaque item final a été tenté au scraping ; les échecs sont marqués plutôt qu'invisibles.
- Les champs formels manquants deviennent actionnables via CSV + fiche app.

## Limites

- Certains sites bloquent le scraping ou sont très JS-heavy : ils restent `scrape_failed` ou incomplets.
- Certains liens enfants extraits d'agrégateurs restent eux-mêmes des pages d'agrégateur ; l'UI les signale.
- Les regex prix/capacité peuvent capter du bruit ; chaque champ extrait doit être considéré comme “à vérifier” tant que non confirmé.
- La prochaine passe utile est de filtrer : `Candidats Beyond` + `non agrégateur` + `<= 5 km Cachan/Châtillon` + `prix/capacité manquants`, puis prioriser les emails/appels.
