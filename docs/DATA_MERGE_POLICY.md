# Data merge policy — protection des données utilisateur

## Règle fondamentale

Une relance sourcing ne doit jamais écraser les données ajoutées par l'utilisateur : statuts, notes, événements, relances, favoris, overrides contact/prix/capacité/adresse, fiabilité source.

## Couches

```text
canonical venue data : données importées / sourcées
user overlay         : données utilisateur protégées
suggested updates    : propositions à examiner
```

## Décisions de merge

### 1. Champ canonique vide + aucun override utilisateur

Action : `safe_canonical_update`.

Exemple : `canonical_contact` est vide, `contactOverride` est vide, une source officielle fournit un email. On peut remplir le canonical.

### 2. Override utilisateur présent

Action : `suggest`.

Exemple : Anthony a saisi `Marie 06...` comme contact corrigé. Une nouvelle source trouve `standard@mairie.fr`. On garde le contact utilisateur et on crée une suggestion.

### 3. Champ canonique déjà rempli

Action : `suggest` sauf valeur identique.

Le sourcing ne remplace pas silencieusement une valeur existante par une autre.

### 4. Lieu rejeté / utilisé / accepté

Action : `suggest` uniquement.

Les lieux à statut utilisateur fort sont protégés : `rejected`, `used`, `accepted`.

### 5. Doublon probable

Action : marquer candidat `duplicate_suspect`, jamais fusionner sans validation humaine.

## Champs mappés

```text
canonical_contact       <-> contactOverride
canonical_price_text    <-> priceOverride
canonical_capacity_text <-> capacityOverride
canonical_address       <-> addressOverride
```

## Script de référence

La logique pure est dans :

```text
scripts/sourcing/merge_policy.py
```

Elle retourne toujours une décision explicite :

```text
noop
safe_canonical_update
suggest
```

## Pourquoi

La base de sourcing peut être reconstruite. La mémoire utilisateur ne peut pas l'être : appels, notes, relances, vécu terrain, corrections manuelles. Elle est donc prioritaire sur toute donnée collectée automatiquement.
