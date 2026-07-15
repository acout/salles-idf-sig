# Reprise urgente — trouver une salle à plusieurs

Mise à jour : 15 juillet 2026.

## Résultat produit attendu

Le produit n’est pas d’abord une carte ni un CRM. Il doit permettre à Anthony et à ses partenaires de trouver rapidement une salle disponible sans appeler deux fois le même lieu.

La boucle utile est courte :

1. voir toutes les pistes sans perte silencieuse ;
2. commencer par les petites salles les plus plausibles ;
3. mettre 20 pistes en shortlist et répartir les appels ;
4. prendre une salle avant d’afficher son contact ;
5. consigner disponibilité, prix, rappel et note ;
6. faire le point ensemble depuis la même vue.

## Ce qui est prêt

- Catalogue public de **275 salles sur 275 sources**.
- Filtre par défaut sur **209 salles prioritaires** : coordonnées plausibles en Île-de-France et capacité maximale connue inférieure ou égale à 20 personnes, ou capacité inconnue.
- Accès volontaire aux **43 lieux de plus grande capacité** qui peuvent contenir une petite sous-salle.
- Accès en liste aux **23 lieux dont le géocodage est incohérent** ; ils ne sont pas placés sur la carte et aucun itinéraire trompeur n’est proposé.
- Les informations absentes sont signalées par `À compléter` au lieu d’être masquées derrière un tiret.
- Contacts, sources, scores et notes séparés dans une release privée hors du dossier statique.
- Connexion équipe Supabase, shortlist partagée, attribution, verrou d’appel, compte rendu, corrections, notes et point d’équipe.
- Repli automatique du temps réel vers une synchronisation toutes les 10 secondes.
- Déploiement public limité à six fichiers ; les GeoJSON de sourcing ne sont jamais copiés dans le site publié.

## Contrat de release courant

- Release : `dataset-4f757b07859f17eb`
- Catalogue : 275 salles
- Répartition : 209 `priority`, 43 `capacity_over_20`, 23 `geocode_review`
- Exclusions silencieuses : 0
- Manifeste public : `public/dataset-manifest.json`
- Manifeste privé local : `.private-dist/dataset-4f757b07859f17eb/private-manifest.json`

## Plan d’urgence

### Jalon U1 — rendre les 275 pistes utilisables

- [x] Conserver toutes les salles dans le catalogue.
- [x] Appliquer le filtre `Prioritaires` par défaut.
- [x] Expliquer les deux groupes à vérifier et neutraliser les mauvaises positions cartographiques.
- [x] Valider le catalogue public et le paquet statique.
- [ ] Charger la nouvelle release privée dans Supabase et rattacher les 275 salles à la campagne active sans perdre un éventuel suivi existant.
- [ ] Déployer sur le staging GitHub Pages et vérifier le filtre dans un navigateur.

### Jalon U2 — lancer les appels à deux ou trois

- [ ] Finaliser l’activation du compte d’Anthony.
- [ ] Inviter les partenaires et vérifier une connexion réelle pour chacune.
- [ ] Constituer une shortlist initiale de 20 salles disposant d’un contact exploitable.
- [ ] Répartir dix appels par partenaire et tester une prise simultanée sur une même salle.
- [ ] Réaliser les appels et produire le point final uniquement depuis la vue `Point d’équipe`.

Critère de réussite : zéro double appel, chaque appel possède un résultat, et aucune consolidation parallèle dans un tableur ou un fil de messages n’est nécessaire.

### Jalon U3 — fiabiliser le corpus après la première session

- Corriger en priorité les 23 géocodages incohérents.
- Requalifier les 43 lieux de grande capacité au niveau de leurs sous-salles réelles.
- Enrichir d’abord la shortlist et les meilleures pistes : téléphone/contact, capacité de la petite salle, prix, adresse et date de vérification.
- Utiliser les notes de terrain pour corriger la source via les scripts ; ne jamais éditer les GeoJSON générés à la main.
- Ne reprendre le sourcing de nouveaux lieux qu’après mesure des trous réellement bloquants dans les 275 pistes existantes.

## Ordre des améliorations produit

1. **Appelables maintenant** : filtre combinant contact direct, shortlist et statut `À appeler`.
2. **Qualité visible** : compteur des champs manquants et file de correction issue des appels.
3. **Sous-salles** : distinguer un établissement de ses salles quand la capacité globale dépasse 20 personnes.
4. **Prochaine action** : rendre les rappels dus visibles dans la file d’appel.
5. **Historique de campagnes** : créer et archiver une nouvelle recherche sans écraser les résultats précédents.

Les notifications, le MFA, un CRM générique, une refonte cartographique et un nouveau pipeline de sourcing ne bloquent pas la recherche urgente.

## Déploiement et vérification

- Staging : <https://acout.github.io/salles-idf-sig/>
- Projet Supabase : `zluhmjoimpnhpuhynrwg`
- Campagne actuelle avant synchronisation de la release : `027f3ac7-22ba-421f-bf65-761edb4cf3d8`

Vérification locale :

```powershell
python scripts/build_public_private_release.py
python scripts/validate_release.py
python scripts/prepare_public_deploy.py
python scripts/validate_static_site.py
node --check public/js/cockpit.js
```

Une fusion vers `staging` déclenche le déploiement GitHub Pages. Aucun changement n’est poussé directement vers `master`.
