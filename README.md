# Salles IDF — cockpit partagé de recherche de salles

## Objectif

Trouver rapidement une salle abordable en Île-de-France, répartir les appels entre partenaires et conserver un état commun sans appeler deux fois le même lieu.

## État du catalogue

- **275 salles publiques** restent visibles, avec le filtre `Prioritaires` appliqué par défaut mais sans exclusion silencieuse.
- **253 candidates de sourcing** issues des deux lots approuvés (`sourcing_idf` et `banlieue_sud`) sont prêtes à être chargées sans préfiltre dans le Sourcing Inbox partagé.
- Après la migration et l’import distants, le catalogue authentifié couvrira **528 pistes**. iFlow Arcueil fait partie du lot vérifié.
- Les candidates rejetées ou marquées comme doublons sont masquées du cockpit, mais leur décision et leur historique restent conservés dans Supabase.

## Boucle d'utilisation

1. Se connecter avec un compte membre actif.
2. Ouvrir `Sourcing` pour rechercher, filtrer et prendre en charge une candidate.
3. Compléter le contact, la capacité, le prix ou la source, puis valider la piste.
4. Utiliser `Envoyer aux appels` pour l'ajouter à la campagne active.
5. Dans le cockpit, prendre la salle avant l'appel, consigner le résultat et préparer le point d'équipe.

Le temps réel est utilisé quand il est disponible. Une synchronisation toutes les 10 secondes prend le relais en cas de dégradation.

## Architecture

- **Frontend** : HTML/CSS/JavaScript sans framework, Leaflet 1.9.4 et tuiles OpenStreetMap.
- **Catalogue statique** : `public/salles_catalog_public.geojson`, généré depuis les données source par `scripts/build_public_private_release.py`.
- **Collaboration** : Supabase Auth, Postgres, RLS, RPC et Realtime.
- **Sourcing** : tables `sourcing_candidates`, `source_observations`, `candidate_evidence` et `sourcing_events`.
- **Déploiement staging** : GitHub Pages depuis la branche `staging`.

## Lancer localement

Mode public en lecture seule :

```powershell
$python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $python scripts/build_public_private_release.py
& $python scripts/write_runtime_config.py --mode read_only --app-release local
& $python scripts/prepare_public_deploy.py
& $python -m http.server 8123 --directory .deploy-dist --bind 127.0.0.1
```

Ouvrir <http://127.0.0.1:8123/>.

Pour le mode partagé, définir `SUPABASE_URL` et `SUPABASE_ANON_KEY`, puis générer la configuration avec `--mode shared`. La clé `SUPABASE_SERVICE_ROLE_KEY` est réservée aux scripts administrateur locaux et ne doit jamais être publiée.

## Mise en service du Sourcing Inbox

Respecter cet ordre pour éviter de publier une interface qui attend un contrat de base de données absent :

```powershell
$python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
supabase link --project-ref <project-ref>
supabase db push
& $python scripts/build_public_private_release.py
# Si les 275 salles ne sont pas déjà rattachées à la campagne active :
& $python scripts/admin_bootstrap_supabase.py --owner "Anthony=<email>" --private-manifest .private-dist/dataset-4f757b07859f17eb/private-manifest.json
& $python scripts/admin_import_sourcing_candidates.py --private-manifest .private-dist/dataset-4f757b07859f17eb/private-manifest.json --dry-run
& $python scripts/admin_import_sourcing_candidates.py --private-manifest .private-dist/dataset-4f757b07859f17eb/private-manifest.json
```

L'import est additif et rejouable. Il bloque si les 253 candidates ne sont pas présentes, si une identité est dupliquée, si une ligne part en quarantaine ou si iFlow Arcueil manque. Le lancement réel requiert `SUPABASE_URL` et `SUPABASE_SERVICE_ROLE_KEY` dans l'environnement local.

Après validation de la parité distante, fusionner la branche vers `staging`. Le workflow écrit `runtime-config.js`, construit une allowlist de **7 fichiers** et déploie GitHub Pages. Les GeoJSON de sourcing et les artefacts privés ne sont jamais copiés dans le site public.

## Référence des écritures Sourcing

Toutes les écritures exigent un membre actif et passent par des RPC ; les tables restent en lecture seule côté navigateur. `p_operation_id` rend une relance idempotente et `p_expected_version` bloque l’écrasement d’une modification concurrente.

| RPC | Paramètres métier | Effet |
|-----|-------------------|-------|
| `create_sourcing_candidate` | `p_payload` | Crée une candidate et sa première observation manuelle. |
| `claim_sourcing_candidate` | `p_candidate_id`, `p_expected_version` | Attribue la candidate au membre courant et la passe en revue. |
| `update_sourcing_candidate` | `p_candidate_id`, `p_expected_version`, `p_patch` | Corrige uniquement les champs autorisés et ajoute les preuves manuelles associées. |
| `set_sourcing_review_status` | candidate, version, statut, détails | Valide, rejette avec motif ou marque un doublon avec une cible existante. |
| `promote_sourcing_candidate` | `p_candidate_id`, `p_expected_version` | Exige le statut `validated`, rattache la salle à la campagne active et la rend visible dans le cockpit. |

Les statuts terminaux `rejected` et `duplicate` ne peuvent pas être réouverts. En cas de conflit de version, recharger la candidate avant de retenter l’action.

## Vérifications

```powershell
$python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $python scripts/validate_release.py
& $python scripts/validate_static_site.py
& $python -m unittest tests/test_sourcing_import.py
node --check public/js/cockpit.js
node --check public/js/sourcing-inbox.js
node --test tests/sourcing-inbox.test.js
supabase db start
supabase test db
supabase stop --no-backup
```

## Documentation

- [État du projet](PROJECT_STATUS.md) et [reprise urgente](docs/URGENT_HANDOFF.md)
- [Entonnoir de sourcing et traçabilité](docs/SMART_SOURCING_FUNNEL_AND_LINEAGE.md)
- [Politique de fusion](docs/DATA_MERGE_POLICY.md), [taxonomie Beyond](docs/BEYOND_VENUE_TAXONOMY.md) et [roadmap sourcing](docs/SOURCING_ROADMAP.md)
- Historique des runs : [2026-06-19](docs/SOURCING_RUN_20260619.md), [banlieue sud](docs/SOURCING_RUN_20260620_BANLIEUE_SUD.md), [enrichissement formel](docs/SOURCING_RUN_20260620_FORMAL_ENRICHMENT.md), [qualification location](docs/SOURCING_RUN_20260620_RENTAL_QUALIFICATION.md) et [smart funnel lot 1](docs/SOURCING_RUN_20260620_SMART_FUNNEL_LOT1.md)
- [Backlog explicite](TODOS.md) et prompts de collecte historiques : [Paris](agent_prompts/collect_paris.md), [petite couronne](agent_prompts/collect_petite_couronne.md), [grande couronne](agent_prompts/collect_grande_couronne.md), [outils SIG](agent_prompts/tools_sig.md)
