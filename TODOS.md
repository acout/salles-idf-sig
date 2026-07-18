# TODOS

## Sourcing

### Publier les candidates validées dans le catalogue statique

**What:** Concevoir en V1.1 une publication versionnée d'une candidate validée vers le GeoJSON public.

**Why:** La V1 rend une salle visible et appelable dans le cockpit privé, mais ne modifie pas encore les 275 salles du catalogue statique.

**Context:** Partir du dernier manifeste valide, générer des artefacts immuables, préserver les identifiants, valider la cardinalité et prévoir un rollback avant toute promotion du manifeste. Ne pas commencer ce chantier avant d'avoir validé le modèle d'identité et la promotion Supabase sur des cas réels.

**Effort:** L
**Priority:** P2
**Depends on:** Adoption et validation du Sourcing Inbox V1

### Automatiser la découverte et le rafraîchissement des sources

**What:** Ajouter des connecteurs de recherche, une extraction sécurisée des pages et un rafraîchissement périodique des sources.

**Why:** Alimenter l'Inbox régulièrement sans dépendre uniquement de la saisie manuelle.

**Context:** Le flux manuel doit d'abord révéler les champs et sources réellement utiles. L'automatisation devra traiter les doublons, la qualité variable, les délais, les redirections et le blocage des réseaux privés avant de télécharger du contenu.

**Effort:** XL
**Priority:** P3
**Depends on:** Plusieurs semaines d'utilisation du flux manuel et un corpus de bons et mauvais exemples

### Structurer les établissements et leurs salles

**What:** Introduire, si les cas réels le justifient, une relation structurée entre un établissement et ses différentes salles louables.

**Why:** Une source peut décrire un lieu global alors que plusieurs espaces distincts ont leurs propres capacités, contacts et disponibilités.

**Context:** La V1 conserve un candidat simple et un lien éventuel vers une salle existante. Évaluer ce modèle sur au moins 20 cas multi-salles avant d'ajouter une hiérarchie, des héritages de coordonnées ou des règles de fusion et scission.

**Effort:** XL
**Priority:** P3
**Depends on:** Revue de 20 cas multi-salles dans le Sourcing Inbox

## Completed

_Aucun élément terminé pour le moment._
