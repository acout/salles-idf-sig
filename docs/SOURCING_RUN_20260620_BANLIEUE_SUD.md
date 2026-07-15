# Sourcing run — 2026-06-20 — Banlieue sud proche Cachan / Châtillon

## Pourquoi ce run

Anthony a signalé que la carte montrait trop peu de points en banlieue, notamment près de Cachan et Châtillon. Diagnostic : le run précédent avait bien ajouté 193 candidats sourcing Beyond, mais ils provenaient majoritairement de snippets web sans adresse exploitable. Résultat : 193 candidats dans la liste, mais 0 point candidat cartographié.

La correction produit est donc : le sourcing doit être pensé comme une **couche SIG additive**, pas comme un onglet d'import séparé, et chaque run doit maximiser le nombre de candidats géocodés sans écraser la base existante.

## Zone ciblée

Corridor sud proche Paris :

```text
Cachan
Châtillon
Bagneux
Montrouge
Arcueil
Gentilly
Villejuif
Le Kremlin-Bicêtre
Malakoff
Clamart
Bourg-la-Reine
Sceaux
L'Haÿ-les-Roses
Fontenay-aux-Roses
Vanves
Issy-les-Moulineaux
Antony
```

## Méthode

Requêtes web ciblées par commune et catégories Beyond-compatible :

```text
studio danse location salle
salle yoga location
dojo location salle
MJC maison associations location salle
```

Chaque résultat accepté est stocké comme `source_record`, avec URL source, snippet d'évidence, commune cible, département, et géocodage BAN quand possible.

## Fichiers créés / mis à jour

```text
data/source_records/banlieue_sud_targeted_20260620.json
data/source_records/banlieue_sud_targeted_20260620.summary.json
data/source_records/combined_beyond_idf_20260620.json
data/source_records/combined_beyond_idf_20260620.summary.json
data/candidates/candidates_20260620.json
data/candidates/candidates_20260620.csv
data/import_queue/duplicates_20260620.json
data/import_queue/report_20260620.json
data/import_queue/import_queue.csv
public/import_queue.geojson
scripts/sourcing/merge_source_records.py
```

## Résultats

### Collecte ciblée banlieue sud

```json
{
  "queries": 45,
  "records": 149,
  "geocoded": 84
}
```

### Queue combinée IDF + banlieue sud

```json
{
  "input_records": 359,
  "normalized_candidates": 359,
  "deduped_candidates": 334,
  "intra_duplicates": 25,
  "existing_matches": 0,
  "import_queue": 334,
  "mapped_import_queue": 83,
  "unmapped_import_queue": 251,
  "by_department_mapped": {
    "92": 45,
    "94": 38
  },
  "high_fit_80_plus": 64,
  "medium_fit_60_plus": 283
}
```

Top villes cartographiées côté candidats :

```json
{
  "Le Kremlin-Bicêtre": 12,
  "Clamart": 11,
  "Villejuif": 10,
  "Bourg-la-Reine": 9,
  "Malakoff": 7,
  "Châtillon": 6,
  "Bagneux": 6,
  "Gentilly": 6,
  "Cachan": 5,
  "Montrouge": 5,
  "Arcueil": 5,
  "Sceaux": 1
}
```

## Impact carte

Avant ce run :

```text
Candidats sourcing cartographiés : 0
```

Après ce run :

```text
Candidats sourcing cartographiés : 83
Candidats <= 8 km de Cachan : 83
Candidats <= 8 km de Châtillon : 83
```

La carte doit donc maintenant afficher une vraie densité violette autour de la banlieue sud, sous le filtre :

```text
Source de données → Tout : salles + candidats Beyond
```

ou :

```text
Source de données → Candidats sourcing Beyond uniquement
```

## Routine ré-exécutable

Pour ajouter une nouvelle vague sans supprimer les anciennes :

```bash
python3 scripts/sourcing/merge_source_records.py \
  data/source_records/systematic_beyond_idf_20260619.json \
  data/source_records/banlieue_sud_targeted_20260620.json \
  --output data/source_records/combined_beyond_idf_YYYYMMDD.json \
  --summary-output data/source_records/combined_beyond_idf_YYYYMMDD.summary.json

python3 scripts/sourcing/build_import_queue.py \
  data/source_records/combined_beyond_idf_YYYYMMDD.json \
  --date YYYYMMDD
```

Cette routine :

- garde les anciens `source_records` ;
- déduplique au niveau source puis candidat ;
- reconstruit `import_queue.csv` et `public/import_queue.geojson` ;
- n'écrit pas dans `data/salles_all_idf.csv` ;
- n'écrit pas dans `public/salles_all_idf.geojson` ;
- ne touche pas au CRM localStorage utilisateur.

## Limites qualité

Ce run augmente fortement la densité cartographique, mais beaucoup de records restent à qualifier :

- certains résultats sont des pages annuaires ou génériques “location de salle” ;
- contacts/prix/capacités restent majoritairement vides ;
- il faut une prochaine passe d'enrichissement sur les candidats high-fit + proches Cachan/Châtillon.

La bonne prochaine passe est donc :

```text
prendre les 30 meilleurs candidats <= 5 km Cachan/Châtillon
→ ouvrir les sites sources
→ extraire contact/prix/capacité/conditions
→ marquer source fiable/incertaine
→ générer suggested_updates si doublon probable
```
