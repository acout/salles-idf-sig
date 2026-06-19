# Beyond venue taxonomy

## Définition

Un lieu Beyond-compatible permet de bouger, parler, interagir, former un cercle, faire des exercices corporels ou émotionnels, éventuellement mettre une musique légère, dans un espace suffisamment vide/modulable et confidentiel.

## Très bon fit

- studio de danse
- studio yoga
- dojo
- salle de mouvement
- salle de répétition théâtre
- centre bien-être avec salle vide
- MJC / centre social avec salle d'activité
- maison des associations avec salle polyvalente vide

## Mauvais fit par défaut

- coworking corporate
- salle de réunion avec table fixe
- hôtel / séminaire premium
- restaurant / bar bruyant non confidentiel
- salle mariage / réception événementielle

## Tags d'activité

```text
dance, yoga, dojo, movement, theatre, circle, meditation, bodywork,
music_allowed, voice_allowed, group_interaction
```

## Tags d'espace

```text
empty_room, open_floor, wood_floor, tatami, mirrors, modular,
chairs_available, tables_optional, natural_light, private, quiet
```

## Contraintes

```text
no_noise, no_music, tables_fixed, association_only, requires_insurance,
limited_evening_access, premium_price, unclear_booking, coworking_corporate
```

## Scores

### `fit_beyond_score`

Mesure l'adéquation intrinsèque avec les ateliers Beyond. Les studios danse/yoga/dojos, sols adaptés, espaces vides et preuves de mouvement montent le score. Coworking, tables fixes, premium et bruit interdit le baissent.

### `confidence_score`

Mesure la fiabilité de la source : site officiel/direct, municipal, agrégateur, OSM, blog.

### `actionability_score`

Mesure si Anthony peut agir maintenant : contact, prix, capacité, adresse, site, source officielle.

## Exemples

### High fit

```text
Studio danse avec parquet, miroirs, salle vide, location ponctuelle, contact direct.
```

Tags : `dance`, `movement`, `open_floor`, `wood_floor`, `mirrors`.

### Medium fit

```text
Salle municipale polyvalente, prix bas, conditions associatives floues.
```

Tags : `circle`, `modular`, contrainte `association_only` / `unclear_booking`.

### Low fit

```text
Salle de réunion coworking 12 places avec table fixe et écran.
```

Catégorie `coworking`, contraintes `tables_fixed`, `coworking_corporate`.

## Source de vérité config

```text
config/sourcing_taxonomy.yaml
```
