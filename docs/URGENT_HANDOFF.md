# Reprise urgente — cockpit d’appels salles IDF

Mise à jour : 14 juillet 2026.

## Ce qui est prêt

- Carte et liste publiques de 209 pistes exploitables : coordonnées plausibles en Île-de-France et capacité maximale connue ≤20 personnes.
- Contacts, sources, scores et notes séparés dans une release privée hors du dossier statique.
- Connexion équipe Supabase, shortlist partagée, attribution, verrou d’appel de 7 minutes, compte rendu, corrections, notes et point d’équipe.
- Repli automatique du temps réel vers une synchronisation toutes les 10 secondes.
- Déploiement limité à six fichiers publics. Les anciens GeoJSON de sourcing ne sont jamais copiés dans le site publié.
- Contrôles automatiques : contrat de données, JavaScript, fuite d’artefacts privés et fichiers critiques.

## Contrats de release actuels

- Release : `dataset-8e58b6aba80910a8`
- Salles publiées : 209 sur 275 sources
- Exclusions : géocodages hors Île-de-France et salles explicitement supérieures à 20 personnes
- Manifeste public : `public/dataset-manifest.json`
- Manifeste privé local : `.private-dist/dataset-8e58b6aba80910a8/private-manifest.json`

## Activation Supabase

1. Créer un projet Supabase dédié.
2. Appliquer `supabase/migrations/20260714_venue_cockpit.sql` dans le SQL Editor.
3. Renseigner localement `SUPABASE_URL` et `SUPABASE_SERVICE_ROLE_KEY` sans les committer.
4. Initialiser les membres et charger la release privée :

```powershell
python scripts/admin_bootstrap_supabase.py `
  --private-manifest .private-dist/dataset-8e58b6aba80910a8/private-manifest.json `
  --owner "Anthony=adresse-owner@example.com" `
  --member "Partenaire 1=partenaire1@example.com" `
  --member "Partenaire 2=partenaire2@example.com" `
  --campaign-name "Recherche urgente de salle" `
  --invite-missing
```

Le script invite les comptes absents, charge les fichiers dans le bucket privé et initialise les 209 suivis. Il n’affiche aucun mot de passe ni clé.

## Activation GitHub / Scaleway

Variables de l’environnement GitHub `staging` :

- `APP_MODE=shared`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SCALEWAY_REGION=fr-par`
- `SCALEWAY_BUCKET_STAGING=salles-idf-staging`

Secrets :

- `SCALEWAY_ACCESS_KEY`
- `SCALEWAY_SECRET_KEY`

Une fusion vers `staging` déclenche ensuite le déploiement. Le workflow publie `.deploy-dist/`, jamais le dossier `public/` complet.

## Blocages externes constatés

- Le dépôt GitHub est encore public : les anciens contacts déjà versionnés restent accessibles dans l’historique. Il faut le rendre privé avant d’ajouter de nouvelles données sensibles.
- Le compte GitHub actuellement connecté, `anthco`, n’a que le droit de lecture sur `acout/salles-idf-sig`. Il ne peut ni pousser, ni modifier la visibilité, ni configurer les secrets.
- Aucune configuration Supabase ou Scaleway utilisable n’est disponible dans l’environnement local actuel.

## Vérification locale

```powershell
python scripts/build_public_private_release.py
python scripts/validate_release.py
python scripts/write_runtime_config.py --mode read_only --app-release local
python scripts/prepare_public_deploy.py
node --check public/js/cockpit.js
```

Servir ensuite `public/` sur `http://127.0.0.1:8765/` pour la consultation locale.
