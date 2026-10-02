# RDC39-Calepin

Fork de Calepin pour une équipe de terrain (mission RDC). Le cadrage détaillé (note de passation) est volontairement gardé hors du dépôt, qui est public.

Il est hébergé dans le sous-dossier `rdc39/` du dépôt Calepin. Une fois GitHub Pages actif, l'URL est `https://goffinm.github.io/calepin/rdc39/`. Le Calepin personnel ne contient aucun lien vers cette app.

## Ce qui change par rapport à Calepin

| | |
|---|---|
| **Capture** | Seuls restent : Dicter, Photo, Note texte, Importer un document, Joindre un fichier. Enregistrer, Transcrire (léger ou IA), Importer audio et « Transcrire tout & exporter » sont retirés. Le modèle de données reste celui de Calepin. |
| **Code d'accès** | Écran de code au premier lancement. Le code est validé par le relais (`/validate-code`) à chaque ouverture quand le réseau est disponible, puis revalidé au retour du réseau. Hors ligne, l'app reste utilisable 14 jours après la dernière validation réussie. Un code révoqué verrouille l'app au prochain contact avec le relais. Les données restent alors sur l'appareil. |
| **Synthèse IA** | Aucune clé sur le téléphone : les clés sont des secrets du Worker. La synthèse se lance uniquement avec le bouton du rapport, jamais automatiquement. |
| **Synchronisation** | Niveau 2. Chaque visite est marquée ⏳ (en attente) ou ✓ (envoyée). L'envoi est automatique à l'ouverture, au retour du réseau, au retour au premier plan, et environ 2 minutes après une modification, tant que l'app est ouverte. Un bouton « Envoyer maintenant » sert de repli dans Réglages. |
| **Carte** (icône 🗺️) | Consultation et navigation uniquement. Elle affiche les 10 couches du projet et les points déjà relevés par l'équipe (taper un point ouvre le relevé). Le panneau de couches a des cases à cocher et se réordonne en glissant, au doigt ou à la souris. La position GPS s'affiche en direct. Un bouton « Télécharger pour le terrain » met en cache le fond OSM de la zone (zoom 12 à 17, 1 139 tuiles, environ 25 Mo). Ce téléchargement n'est jamais automatique. |

## Mise en service (environ 15 minutes)

1. **Espace KV** : Cloudflare → Storage & Databases → KV → *Create* → nom `rdc39-digests`.
2. **Worker** : Workers & Pages → Create → *Hello World* → nom discret (ex. `terrain-relais`). Collez le contenu de [`relais/relais-rdc39-worker.js`](relais/relais-rdc39-worker.js), puis *Deploy*.
3. **Liaison KV** : Worker → Settings → Bindings → *KV namespace* → nom de variable `DIGESTS` → espace `rdc39-digests`.
4. **Variables** : Worker → Settings → Variables and Secrets.
   - `ACCESS_CODES` (Secret) : un ou plusieurs codes séparés par des virgules. Avec un code par personne, vous pouvez révoquer quelqu'un sans toucher aux autres.
   - `ANTHROPIC_API_KEY` et/ou `OPENAI_API_KEY` / `OPENROUTER_API_KEY` (Secret).
   - `GRACE_DAYS` (texte, facultatif, 14 par défaut).
   - `ALLOWED_ORIGIN` (texte, facultatif) : `https://goffinm.github.io`, pour refuser les appels venant d'autres sites.
5. **Brancher l'app** : copiez l'URL du Worker dans la constante `RELAY_URL` de `index.html` (cherchez `const RELAY_URL = ""`), puis commit et push.
   Tant que la constante est vide, l'écran de code propose un champ « URL du relais ». C'est pratique pour tester avant de figer l'URL.
6. **Fournisseur IA** : par défaut l'app utilise Anthropic (Claude Haiku 4.5). Il se change dans Réglages → Synthèse IA, sur chaque appareil.

### Révoquer l'accès

Retirez le code de `ACCESS_CODES` (ou videz la variable) et enregistrez. Aucun redéploiement n'est nécessaire.
- Un appareil connecté est verrouillé dès sa prochaine ouverture ou son prochain retour réseau.
- Un appareil resté hors ligne est verrouillé au plus tard 14 jours après sa dernière validation.

Attention : les visites encore ⏳ sur un appareil verrouillé ne peuvent plus être envoyées. Vérifiez que tout est envoyé avant de révoquer en fin de mission.

### Récupérer les relevés

Cloudflare → KV → `rdc39-digests`. Chaque visite a une entrée `visite:<uid>`, dont les métadonnées sont visibles sans ouvrir la valeur : repère, date, appareil, date de réception, taille, nombre d'entrées, corbeille.

La valeur est le digest JSON complet, au même format que l'export « digest » de Calepin. Il contient en plus `dossier`, `tags`, `corbeille`, `appareil`, `versionApp` et `genereLe`. Les photos et pièces jointes sont incluses en base64.

Chaque envoi écrase la version précédente de la même visite. Une visite supprimée définitivement sur un téléphone n'est **pas** supprimée de KV : c'est voulu, pour ne jamais perdre de données. Une visite mise à la corbeille porte `corbeille` dans son digest.

## Points d'attention

- **Même origine que le Calepin personnel** (`goffinm.github.io`). La base locale et les réglages sont séparés :
  - base IndexedDB `rdc39-calepin` ;
  - clés `rdc39_*`.

  Les deux apps peuvent donc coexister sur un même téléphone sans se mélanger. Les caches de service worker, eux, sont partagés par origine. C'est pourquoi `sw.js` (racine) ne supprime désormais que ses propres caches `calepin-*`. Sans ce correctif, une mise à jour du Calepin personnel aurait effacé le fond de carte hors ligne de RDC39.
- **Discrétion** : le dépôt est public, donc `rdc39/` est visible par quiconque parcourt le dépôt. La page porte `noindex`. Les couches GeoJSON (`layers/`) sont des fichiers statiques publics, servis sans code d'accès, comme toute page GitHub Pages. Les données (KV) et les clés (Worker) restent privées derrière le code. Un nom de domaine dédié pourra être branché plus tard sans changer le code, à condition de mettre à jour `ALLOWED_ORIGIN`.
- **Limites du palier gratuit Cloudflare** :
  - 1 000 écritures KV par jour ;
  - 25 Mo par valeur. Une très grosse visite (nombreuses photos en qualité « Détaillée ») serait refusée (413) et resterait ⏳.
- **Fond de carte** : au-delà du zoom 17, les tuiles z17 sont agrandies, ce qui donne le même rendu en ligne et hors ligne.

## Tests effectués

Tests réalisés avec Chromium headless et un relais simulé qui exécute le Worker sous Node avec un faux KV :
- code refusé, puis accepté ;
- après révocation, l'app est verrouillée avec le message dédié ;
- création d'une visite et d'une note avec GPS ;
- synchronisation : la visite passe de ⏳ à ✓ et l'entrée KV apparaît avec ses métadonnées ;
- carte : les 10 couches et le point relevé s'affichent, le réordonnancement par glisser est mémorisé ;
- téléchargement des 1 139 tuiles ;
- mode avion : l'app et la carte (couches et tuiles) s'ouvrent hors ligne.

Non testé ici : l'appel réel aux API IA, et la dictée vocale, inchangée depuis Calepin.
