# PROJECT_STATUS.md — salles-idf-sig

## Overview

| Item | Status |
|------|--------|
| Project | salles-idf-sig |
| Type | Shared calling cockpit + public map (Leaflet + Supabase) |
| Repo | `acout/salles-idf-sig` on GitHub |
| Last updated | 2026-07-18 |

## Urgent delivery status — 2026-07-18

- **Code:** Sourcing Inbox, contrat Supabase, import déterministe et garde-fous de déploiement sont implémentés et testés localement.
- **Catalogue public:** 275 salles, release déterministe `dataset-4f757b07859f17eb`, filtre par défaut sur 209 priorités.
- **Catalogue authentifié attendu:** 275 salles + 253 candidates de sourcing = 528 pistes, sans préfiltre des lots approuvés et avec iFlow Arcueil.
- **Déploiement public:** allowlist de sept fichiers ; aucun GeoJSON de sourcing ni artefact privé n'est publié.
- **Blocage opérationnel restant:** appliquer la migration distante, importer et vérifier les 253 candidates, puis seulement déployer le frontend partagé sur `staging`.
- **Runbook:** voir `docs/URGENT_HANDOFF.md`.

## Deployments

| Environment | Branch | URL | Method |
|-------------|--------|-----|--------|
| Local | branche de travail | `http://127.0.0.1:8123/` | serveur statique Python |
| Staging | `staging` | `https://acout.github.io/salles-idf-sig/` | GitHub Actions → GitHub Pages |
| Production | `master` | à confirmer | décision et déploiement manuel d'Anthony |

## Data Status

- **Catalogue statique:** 275 salles, réparties en 209 `priority`, 43 `capacity_over_20` et 23 `geocode_review`.
- **Candidates sourcing:** 253 entrées des lots `sourcing_idf` et `banlieue_sud`, avec identité stable et import additif/rejouable.
- **Départements:** 75, 77, 78, 91, 92, 93, 94, 95.
- **Traçabilité:** observation, preuves par champ, événements de revue et décisions terminales conservés séparément.

## Product Status

Implemented:

- [x] Carte, liste, file d'appels et point d'équipe partagés
- [x] Connexion Supabase et contrôle d'accès des membres actifs
- [x] Shortlist, attribution, verrou d'appel, compte rendu, notes et historique
- [x] Catalogue public complet avec filtre `Prioritaires` par défaut
- [x] Sourcing Inbox paginé avec recherche et filtres par statut, département, responsable et données manquantes
- [x] Création manuelle, prise en charge, correction, validation, rejet, doublon et promotion vers la campagne active
- [x] Synchronisation Realtime avec repli par polling toutes les 10 secondes
- [x] Import déterministe des 253 candidates historiques, contrôle de parité distante et présence d'iFlow Arcueil
- [x] RLS, écritures via RPC, versions optimistes et opérations rejouables
- [x] Tests navigateur unitaires, import Python et 47 contrats pgTAP sur base isolée
- [x] Déploiement staging limité à sept fichiers publics

## Next Steps

1. Appliquer `20260716_sourcing_inbox.sql` au projet Supabase distant.
2. Exécuter l'import des 253 candidates et vérifier la parité distante.
3. Fusionner vers `staging` et vérifier une session authentifiée sur GitHub Pages.
4. Inviter les partenaires, constituer une shortlist de 20 pistes et tester deux prises simultanées.
5. Lancer les appels et tenir le point d'équipe uniquement dans l'application.

Les améliorations non urgentes restent dans [TODOS.md](TODOS.md).
