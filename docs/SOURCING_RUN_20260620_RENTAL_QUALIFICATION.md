# Sourcing run — 2026-06-20 — Rental possibility qualification

## Pourquoi ce lot

Anthony a demandé de vérifier une hypothèse métier essentielle : un lieu peut être intéressant (yoga, danse, fitness, dojo) sans proposer de location/privatisation de salle. Exemples typiques : Fitness Park, salles de sport à abonnement, pages de cours de yoga/danse sans mention de location de salle.

La pipeline devait donc ajouter une étape distincte :

```text
Est-ce qu'une location de salle semble réellement possible ?
```

## Nouvelle étape pipeline

Script ajouté :

```text
scripts/sourcing/qualify_rental_possibility.py
```

Il classe chaque record avec :

```text
rental_possible_status      possible | unclear | unlikely
rental_possible_confidence  high | medium | low
rental_positive_signals     signaux trouvés sur la page
rental_negative_signals     signaux défavorables
rental_email_question       question à poser si non confirmé
rental_decision_needed      yes/no
```

## Signaux positifs

Exemples de motifs qui classent en `possible` :

```text
location de salle
location de salles
salle à louer
louer une salle
louer un studio
location studio
privatisation
privatiser
mise à disposition
réservation de salle
tarifs de location
demande de location
accueil stages / ateliers / événements
espace à louer / privatiser / réserver
```

## Signaux négatifs

Exemples de motifs qui classent en `unlikely` si aucun signal positif clair n'est trouvé :

```text
Fitness Park
salle de sport
club de sport
abonnement
adhérents uniquement
cours collectifs
planning des cours
cours de yoga
cours de danse
inscription aux cours
coaching personnel
acheter un pass
réserver un cours
```

Règle conservative : si une page contient à la fois des cours et une mention explicite de location/privatisation, le positif gagne. Beaucoup de studios yoga/danse donnent des cours ET peuvent louer leur salle.

## Résultat sur la queue actuelle

Sur 1042 records source enrichis :

```json
{
  "possible": 440,
  "unclear": 574,
  "unlikely": 28
}
```

Après déduplication/matching vers l'import queue finale :

```json
{
  "import_queue": 834,
  "rental_possible_distribution": {
    "possible": 337,
    "unclear": 469,
    "unlikely": 28
  },
  "rental_confidence_distribution": {
    "high": 91,
    "medium": 274,
    "low": 469
  }
}
```

## CSV email mis à jour

Nouveau CSV :

```text
data/import_queue/email_questions_20260620_rental.csv
```

Il inclut maintenant :

```text
rental_possible_status
rental_possible_confidence
rental_positive_signals
rental_negative_signals
email_questions
```

Résumé :

```json
{
  "rows_needing_email_or_rental_check": 707,
  "rental_unclear_or_unlikely": 497
}
```

## UI ajoutée

Nouveaux filtres :

```text
Location possible
Location à vérifier
Probablement non louable
```

Nouveaux badges :

```text
Location possible      vert
Location à vérifier    jaune
Probablement non louable rouge
```

Dans la fiche détail `Scraping formel`, l'app affiche maintenant :

```text
Location : Location possible / à vérifier / probablement non louable
Confiance
Signaux location +
Signaux location -
Question email associée
```

## Pipeline réexécutable

Runner ajouté :

```text
scripts/sourcing/run_beyond_pipeline.py
```

Commande type :

```bash
python3 scripts/sourcing/run_beyond_pipeline.py \
  data/source_records/systematic_beyond_idf_20260619.json \
  data/source_records/banlieue_sud_targeted_20260620.json \
  --date YYYYMMDD_rerun \
  --workers 12
```

Le runner exécute :

```text
1. merge_source_records.py
2. enrich_formal_fields.py avec expansion agrégateurs
3. enrich_formal_fields.py sans ré-expansion pour checker chaque item final
4. geocode_source_records.py
5. qualify_rental_possibility.py
6. build_import_queue.py
7. génération email_questions_<date>.csv
```

Cette dynamique est additive et non destructive : elle ne modifie pas la base canonique `salles_all_idf` ni le CRM localStorage.

## Limites

- `unlikely` ne veut pas dire impossible juridiquement : ça veut dire que le site ressemble à une offre de cours/abonnements, sans preuve de location.
- `unclear` veut dire qu'il faut demander explicitement par email.
- Certains agrégateurs créent du bruit ; ils restent marqués `Agrégateur`.
- La prochaine amélioration serait de réduire le bruit en dépriorisant automatiquement les `rental_unlikely` dans le score/actionability.
