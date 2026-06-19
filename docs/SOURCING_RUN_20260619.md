# Sourcing run — 2026-06-19 — Beyond-compatible IDF

## Résumé

Run autonome de sourcing pur orienté espaces compatibles Beyond : danse, yoga, dojos, mouvement, répétition, théâtre, bien-être, MJC/municipal/associatif, espaces vides ou modulables.

Le run respecte la politique de non-écrasement : aucune écriture dans `data/salles_all_idf.csv`, `public/salles_all_idf.geojson` ou dans les données CRM/localStorage utilisateur. Les nouveaux lieux sont placés en import queue.

## Collecte effectuée

### Subagents web

Trois vagues web spécialisées ont été lancées :

1. Paris 75 — danse/yoga/dojos/théâtre/Paris Anim/MVAC/MJC.
2. Petite couronne 92/93/94 — studios, dojos, lieux municipaux/associatifs.
3. Grande couronne 77/78/91/95 — lieux accessibles RER/Transilien, studios, MJC, salles municipales, studios musique/voix.

Ces agents ont produit une liste riche de candidats vérifiés par source URL, notamment des lieux à très forte valeur : Centre de Danse du Marais, Micadanses, Studio l'Envol, Studio Bleu, Dojo Paris, Dojo Goryu, Paris Danse Studio, Centres Paris Anim, La Fabrique de la Danse, Groov'it Dance Studio, MT Art Studio, Comme Vous Émoi, Alemana Danse, Studio 102, Art & Danse Lagny/Meaux, MJC des Tilleuls, Ateliers Petits Pieds Grands Sauts, The Muse Lab, Studio Rambouillet, Belle Fée Danse, Studio Abrace, etc.

### Collecte web systématique

Une collecte automatique catégorie × département a été exécutée avec 48 requêtes web :

- studio danse
- salle yoga
- dojo
- salle répétition théâtre
- salle bien-être
- salle mouvement
- MJC location de salle
- maison des associations salle réservation

Départements : 75, 92, 93, 94, 77, 78, 91, 95.

## Résultat matérialisé

Fichiers créés :

```text
data/source_records/systematic_beyond_idf_20260619.json
data/candidates/candidates_20260619.json
data/candidates/candidates_20260619.csv
data/import_queue/import_queue.csv
data/import_queue/duplicates_20260619.json
data/import_queue/report_20260619.json
public/import_queue.geojson
```

## Métriques vérifiées

```json
{
  "input_records": 210,
  "normalized_candidates": 210,
  "deduped_candidates": 193,
  "intra_duplicates": 17,
  "existing_matches": 0,
  "import_queue": 193,
  "high_fit_80_plus": 32,
  "medium_fit_60_plus": 145,
  "with_contact": 0,
  "with_price": 0,
  "with_capacity": 0
}
```

Note : la collecte systématique matérialisée repose sur les snippets de recherche, donc les champs contact/prix/capacité sont souvent vides. Les subagents web ont toutefois identifié de nombreux contacts/prix/capacités dans leurs rapports. Prochain lot : importer ces rapports enrichis ou relancer une extraction ciblée sur les 32 high-fit.

## Vérifications fortes

Commandes exécutées :

```bash
python3 -m py_compile scripts/sourcing/*.py
python3 scripts/sourcing/build_import_queue.py --demo --date demo_verify
python3 scripts/sourcing/build_import_queue.py data/source_records/systematic_beyond_idf_20260619.json --date 20260619
```

Assertions :

```text
report input_records == 210
report deduped_candidates == 193
report import_queue == 193
GeoJSON features == 193
```

Hashes des fichiers protégés après run :

```text
7a8f38a2f0557eb4b7e85fa65645a683e736dfa46cd8078c2e06ca969af11379  data/salles_all_idf.csv
6f40e8ddfdc5503afd13e2fd2bda954794692f629b9756c6129033adf2a732dd  public/salles_all_idf.geojson
305afdfae11e417abc51244e3ca17d36d5a1b285926405a19ce3d1238469a7de  public/js/app.js
```

## Limites observées

La tentative d'extraction automatique de pages sources via `web_extract` sur les meilleurs candidats a dépassé le timeout. Elle a été abandonnée pour ne pas bloquer le run. À refaire par batches plus petits ou via script HTTP direct ciblé.

## Prochain lot recommandé

1. Créer une vraie `Import Review UI` dans l'app.
2. Importer les résultats enrichis des subagents en `source_records` structurés.
3. Relancer extraction ciblée des 32 candidats `fit_beyond_score >= 80` pour contact/prix/capacité.
4. Ajouter géocodage BAN pour candidats avec adresse exploitable.
5. Générer `suggested_updates` pour les candidats qui matchent déjà une salle existante.
