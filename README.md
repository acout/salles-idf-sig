# Salles IDF — pipeline réutilisable v0

## Objectif

Prospecter des salles privatisables en Île-de-France, les normaliser en CSV/GeoJSON, puis les afficher sur une carte web filtrable avec liens, contacts, pros/cons et scores.

## Artefacts

- `data/salles_idf.csv` — source tabulaire enrichie, éditable.
- `public/salles_idf.geojson` — export cartographique.
- `public/index.html` — carte Leaflet statique.
- `scripts/build_dataset.py` — génération CSV/GeoJSON + géocodage BAN.
- `agent_prompts/` — prompts réutilisables pour relancer des sous-agents par zone.

## Stack retenue

- **CSV maître** pour MVP : portable, versionnable, éditable.
- **API Adresse / BAN** pour géocoder les adresses françaises.
- **GeoJSON** comme format de publication SIG.
- **Leaflet** pour carte custom statique avec filtres par département et popups riches.
- **uMap** possible si besoin d'une publication no-code rapide à partir du GeoJSON.
- **Baserow** recommandé en v1 si plusieurs personnes doivent qualifier/mettre à jour les lieux.

## Schéma de données

Champs principaux :

- `id`, `name`, `category`
- `address`, `city`, `department`, `lat`, `lon`, `geocode_score`, `geocode_label`
- `capacity_text`, `capacity_min`, `capacity_max`
- `website`, `contact`
- `pros`, `cons`
- `source_url`, `confidence`, `quality_score`, `fit_score`, `last_checked`

## Process réutilisable

1. **Collecte par zone**
   - Paris intra-muros.
   - Petite couronne : 92/93/94.
   - Grande couronne : 77/78/91/95.
   - Pour chaque zone : demander JSON strict avec nom, adresse, capacité, site, contact, source, pros/cons, confidence.
   - Si on relance via Claude Code en print mode dans WSL, utiliser le pattern vérifié :
     `env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY -u https_proxy -u http_proxy -u all_proxy claude -p --effort high < prompt.md > raw/name.out 2> raw/name.err`.
     Le premier essai parallèle a échoué avec `tcsetattr: Inappropriate ioctl for device` et fichiers vides ; le smoke corrigé `Réponds uniquement OK` a bien retourné `OK`.

2. **Normalisation**
   - Dédupliquer par `name + postcode/city`.
   - Ne jamais inventer contact/capacité.
   - Mettre `confidence=medium/low` si la source n'est pas officielle ou si la jauge manque.

3. **Géocodage**
   - Script `python3 scripts/build_dataset.py`.
   - Utilise API Adresse avec proxy désactivé pour éviter les erreurs Agent Vault/407.

4. **Scoring**
   - `quality_score` : source, géocodage, contact, capacité.
   - `fit_score` : pertinence métier, capacité, proximité Paris, type de lieu.

5. **Publication**
   - Lancer localement : `cd public && python3 -m http.server 8123 --bind 127.0.0.1`.
   - Ouvrir : `http://127.0.0.1:8123/`.
   - Déployer en statique si besoin : GitHub Pages / Netlify / Vercel / Drive.

## Limites v0

- Corpus initial volontairement qualifié mais non exhaustif : 25 lieux géocodés.
- Grande couronne encore sous-couverte ; à relancer avec sous-agents dédiés par département.
- Les contacts/prix/disponibilités doivent être vérifiés avant prospection commerciale.
- Respecter les licences OSM/open-data et éviter d'industrialiser du scraping agressif de contacts personnels.

## Prochaine itération recommandée

- Monter à 80-120 lieux : 20 Paris, 20 petite couronne, 10 par département grande couronne.
- Ajouter filtres capacité min/max, type, contact présent, score.
- Ajouter statut CRM : `to_check`, `shortlist`, `contacted`, `replied`, `rejected`.
- Ajouter exports : shortlist CSV et fiche Markdown par salle.
