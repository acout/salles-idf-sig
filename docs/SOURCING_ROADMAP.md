# Sourcing roadmap — espaces Beyond-compatible IDF

## Objectif

Construire un pipeline de sourcing exhaustif, relançable et non destructif pour découvrir les meilleurs espaces d'Île-de-France compatibles avec des ateliers Beyond : danse, yoga, dojo, mouvement, interaction, voix, cercle, espaces vides/modulables.

## Principe dur

Le sourcing ne modifie jamais la couche utilisateur. Les notes, statuts, relances, events, favoris et overrides locaux restent dans `user_overlay` / `state.crm` et ne sont jamais écrasés par une nouvelle collecte.

## Architecture cible

```text
source_records  -> données brutes traçables
candidates      -> lieux normalisés, scorés, dédupliqués
venues          -> lieux canoniques visibles dans l'app
user_overlay    -> CRM utilisateur protégé
suggested_updates -> propositions non destructives
```

## Phases

### S0 — Anti-écrasement + modèle source

Livré dans ce lot : schémas JSON, IDs stables, scripts de merge policy. Le but est de pouvoir relancer le sourcing sans polluer ni écraser les données utilisateur.

### S1 — Taxonomie Beyond + scoring

Livré dans ce lot : `config/sourcing_taxonomy.yaml` avec tags d'activité, d'espace, contraintes, catégories, pondérations et règles de démotion.

### S2 — Pipeline candidates / import queue

Créer un flux `data/candidates` -> `data/import_queue/import_queue.csv` + `public/import_queue.geojson`, sans toucher à `salles_all_idf`.

### S3 — Vague Paris high-fit

Sourcing massif ciblé Paris : studios de danse, yoga, dojos, salles de répétition, centres bien-être, Paris Anim, MVAC, MJC, centres sociaux.

Objectif : 300-600 records bruts, 150-250 candidats normalisés, 80-150 lieux high-fit.

### S4 — Import Review UI

Ajouter un onglet Import pour accepter, rejeter, fusionner ou transformer les candidats en `suggested_updates`.

### S5 — Petite couronne Beyond

92 / 93 / 94, priorité aux lieux accessibles métro/RER/tram et aux espaces de mouvement.

### S6 — Grande couronne accessible

78 / 91 / 95 / 77 par axes de transport, recherche de lieux moins chers et plus spacieux.

### S7 — OSM / Overpass chunké + agrégateurs

Compléter par Overpass en petites grilles et par agrégateurs comme signaux de découverte, jamais comme vérité finale.

### S8 — Sourcing continu

Relance mensuelle/manuelle : détecte nouveaux lieux, sources mortes, changements de prix/contact/capacité ; produit import queue + suggestions.

## Source families prioritaires

1. Studios danse / répétition / théâtre
2. Yoga / méditation / bien-être
3. Dojos / arts martiaux / mouvement
4. Paris Anim / MVAC / MJC / centres sociaux
5. Salles municipales / associatives vides
6. OSM / Overpass chunké
7. Agrégateurs comme découverte uniquement

## Commandes actuelles

```bash
python3 scripts/sourcing/build_import_queue.py --demo
python3 -m py_compile scripts/sourcing/*.py
```
