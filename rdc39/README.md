# RDC39-Calepin

Fork de Calepin pour une équipe de terrain (mission RDC). Le cadrage détaillé (note de passation) est volontairement gardé hors du dépôt, qui est public.

Il est hébergé dans le sous-dossier `rdc39/` du dépôt Calepin, à l'adresse `https://goffinm.github.io/calepin/rdc39/`. Le Calepin personnel ne contient aucun lien vers cette app.

## Ce qui change par rapport à Calepin

| | |
|---|---|
| **Visites** | Format libre : un repère, une date, des entrées. Il n'y a plus de catégories (immobilier, véhicule…). Dossiers, tags, corbeille, qualité photo et rapport texte restent inchangés. |
| **🎤 Enregistrer** (capture principale) | Fonctionne sans réseau, pour des prises de plusieurs minutes. L'audio est écrit sur l'appareil toutes les 2 s. Un enregistrement interrompu (app tuée, batterie, appel) est récupéré au lancement suivant, avec la mention « Enregistrement récupéré ». Pendant la capture s'affichent un niveau sonore en direct, la durée et la taille déjà sauvegardée ; l'écran reste allumé. À l'arrêt, une alerte apparaît si rien n'a été capté, ou si l'utilisateur a quitté l'app pendant la capture. Débit d'environ 32 kbit/s, soit à peu près 2,4 Mo pour 10 minutes. |
| **🗣️ Dicter** (secondaire) | Bouton bloqué hors connexion, avec une explication. Une session de reconnaissance par énoncé, relancée automatiquement jusqu'à « Arrêter ». Le texte est ajouté au fur et à mesure (anti-doublon), jamais écrasé, et le brouillon est sauvegardé en continu. Le texte validé s'affiche en noir, le texte provisoire en gris. L'entrée est marquée « dictée, non relue » (`source: "dictee"`). Sous Chrome, l'audio dicté transite par les serveurs de Google : à mentionner dans le briefing. |
| **📍 Point** | Enregistre la position actuelle comme entrée à part entière (repère de crue, pile de pont, départ de ravine…), avec un nom facultatif. L'app écoute le GPS jusqu'à ± 5 m, ou 30 s au plus, garde la meilleure mesure et note sa précision (« ± 4 m »). On peut valider plus tôt. Utilisable pendant un enregistrement. Sur la carte, les points ont un marqueur cerclé de blanc. |
| **Position** | Le statut de localisation est toujours visible : pastille 📍 dans la barre du haut, et ligne en tête de chaque visite (OK ± x m / recherche / indisponible / refusée). Toucher le statut ouvre une explication et un bouton « Réessayer ». Au premier lancement, une fenêtre demande explicitement l'autorisation. Le délai d'attente du GPS passe de 6 s à 20 s, mais une capture n'attend jamais : la dernière mesure de moins d'une minute est réutilisée, sinon l'entrée est enregistrée tout de suite et sa position y est rattachée dès qu'une mesure arrive (pendant 2 minutes au plus). Toute entrée sans position affiche **⚠ sans position**, qui ouvre directement la saisie de position, préremplie avec la position actuelle si elle est connue. |
| **EXIF GPS à l'export** | Chaque JPEG exporté (synchro et digest, export standard, fichiers de la page admin) reçoit un segment EXIF : latitude, longitude, références N/S et E/W, DateTimeOriginal (heure locale) et OffsetTimeOriginal, plus l'altitude et la précision quand elles sont connues. Ces valeurs viennent de la position et de l'horodatage **actuels** de l'entrée ; une correction manuelle de position est donc prise en compte. Tout segment Exif existant est remplacé, y compris le segment vide produit par le canvas de Safari. Une entrée sans position garde sa photo inchangée. Le code est dans `index.html`, entre les marqueurs `EXIF-WRITER-BEGIN` et `EXIF-WRITER-END`. |
| **Autres captures** | 📷 Photo (GPS EXIF repris), 📝 Note texte, 📄 Importer document (.txt), 📎 Joindre un fichier. « Importer audio » est retiré (à confirmer). |
| **IA** | Aucune : pas de clé, pas d'appel, pas de synthèse. Le traitement de l'audio se fait côté Michel, à partir des données récupérées. |
| **Code d'accès** | Validé par le relais à chaque ouverture quand il y a du réseau. Hors ligne, l'app reste utilisable 14 jours après la dernière validation. Un code révoqué verrouille l'app au prochain contact avec le relais ; les données restent sur l'appareil. |
| **Synchronisation** | Niveau 2, **entrée par entrée** : chaque entrée et chaque visite sont marquées ⏳ ou ✓. L'envoi est automatique à l'ouverture, au retour du réseau, au retour au premier plan et environ 2 min après une modification, tant que l'app est ouverte. Un bouton « Envoyer maintenant » se trouve dans Réglages. Un envoi coupé ne fait perdre que l'entrée en cours, qui est renvoyée au prochain essai. |
| **Carte** 🗺️ | Navigation et consultation uniquement : 11 couches du projet (dont la conduite, ajoutée le 05/10), points déjà relevés (un tap ouvre le relevé), position GPS en direct. Le bouton « Télécharger pour le terrain » met en cache le fond OSM de la zone (1 322 tuiles, ~30 Mo ; si le fond avait déjà été téléchargé, retoucher le bouton ne récupère que les tuiles manquantes). |

## Mise en service

Le relais est déjà déployé (`terrain-relais`). **Pour cette version, il faut le mettre à jour** :

1. Collez le nouveau [`relais/relais-rdc39-worker.js`](relais/relais-rdc39-worker.js) dans l'éditeur du Worker, puis *Deploy*.
2. Dans Settings → Variables and Secrets :
   - ajoutez `ADMIN_CODE` (Secret), un code **différent** des codes d'équipe, réservé à la page d'administration ;
   - supprimez les clés IA (`ANTHROPIC_API_KEY`…), devenues inutiles.
3. Vérifiez en ouvrant l'URL du relais dans un navigateur. Vous devez voir : « Codes équipe : oui. Stockage KV : lié. Code admin : oui. »

Autres variables : `ACCESS_CODES` (codes d'équipe séparés par des virgules), `GRACE_DAYS` (facultatif, 14 par défaut) et `ALLOWED_ORIGIN` (facultatif, `https://goffinm.github.io`). La liaison KV reste `DIGESTS` → `rdc39-digests`.

### Révoquer l'accès

Retirez le code de `ACCESS_CODES` et enregistrez, sans rien redéployer. L'appareil est verrouillé à son prochain contact réseau, et au plus tard 14 jours après sa dernière validation. Les entrées encore ⏳ sur un appareil verrouillé ne peuvent plus être envoyées : vérifiez que tout est ✓ avant de révoquer en fin de mission.

### Récupérer les relevés

Utilisez la page **`https://goffinm.github.io/calepin/rdc39/admin.html`** (non liée depuis l'app, protégée par `ADMIN_CODE`). Elle affiche la liste des visites reçues et, pour chacune, deux boutons :
- **Digest JSON** : la visite complète réassemblée (format ci-dessous) ;
- **Fichiers** : audio, photos et pièces jointes, téléchargés un par un avec des noms lisibles.

Dans KV, une visite occupe plusieurs clés : `m:<visite>` (manifeste : métadonnées et liste des entrées) et `e:<visite>:<entrée>` (une clé par entrée). Une entrée supprimée sur le téléphone reste dans KV ; elle est signalée `supprimeeSurTelephone` dans le digest. Une entrée pas encore reçue apparaît dans `entreesManquantes`.

### Format des données : `schemaVersion: 2`

Le format est dérivé du digest v1 de Calepin. Le Calepin personnel et son format v1, consommé par l'outil pompage, ne sont pas modifiés.

```
{ schemaVersion: 2, uid, tag, date, dossier, tags, corbeille, appareil, versionApp, genereLe,
  entries: [ { id, type: "audio"|"photo"|"texte"|"fichier"|"point", horodatage, repere, position, texte,
               // position = { lat, lng } ; pour un point : + accuracy (m) et, si fournie, altitude (m, GPS)
               source?: "dictee", recupere?: true,
               audio?:   { mime, base64, duree },   // NOUVEAU : audio inclus (webm/opus Android, mp4/aac iOS)
               image?:   { mime, base64 },
               fichier?: { nom, mime, base64 } } ] }
```

Changements par rapport à la v1 :
- l'audio est **inclus** ;
- chaque entrée porte un `id` ;
- les champs `category` et `syntheseIA` sont retirés ;
- les champs `dossier`, `tags`, `corbeille`, `appareil`, `versionApp` et `genereLe` sont ajoutés.

L'export manuel « Exporter (digest JSON) », dans chaque visite, produit le même format avec en plus `syntheseBrute`. Il sert de secours si la synchronisation échoue.

## Limites Cloudflare (palier gratuit, vérifiées le 04/10/2026)

- KV : 1 000 écritures par jour, 1 000 listes par jour, 100 000 lectures par jour, 25 Mio par valeur, 1 Go de stockage.
- Chaque entrée envoyée compte pour 1 écriture, chaque visite pour 1 écriture de plus. Exemple : 4 personnes × 5 visites × 30 entrées par jour ≈ 620 écritures. Le quota passe, mais avec une marge limitée.
- Une entrée de plus de 24 Mo serait refusée et resterait ⏳. Cela correspond à environ 1 h 30 d'audio en continu ; ce n'est pas un cas réaliste.

## Points d'attention

- **Même origine que le Calepin personnel** (`goffinm.github.io`). La base (`rdc39-calepin`) et les réglages (`rdc39_*`) sont séparés. Les caches de service worker sont partagés, d'où le correctif dans `sw.js` (racine), qui ne supprime plus que ses propres caches `calepin-*`.
- **Livraison** : incrémenter **ensemble** `APP_VERSION` (`index.html`) et `CACHE_NAME` (`sw.js`), puis relire les deux valeurs. La version s'affiche dans Réglages.
- **Discrétion** : le dépôt et les couches (`layers/`) sont publics. Les données (KV) restent privées derrière les codes.
- **Seuil « aucun son »** (`REC_SILENCE_THRESHOLD` = 0,008) : à calibrer sur un vrai téléphone. Il a été réglé avec un micro simulé (son de test et silence).

## Tests effectués (Chromium headless, relais simulé exécutant le Worker sous Node)

- Accès : code refusé puis accepté. Révocation (test de la version précédente, code inchangé).
- Visite sans catégorie.
- **Enregistrement** de 7 s :
  - morceaux écrits pendant la capture, puis effacés après l'assemblage ;
  - lecteur affiché avec la durée ;
  - niveau sonore visible avec un son de test, alerte avec un vrai silence.
- **Récupération** d'un enregistrement coupé par un rechargement brutal : 6 s récupérées.
- **Dictée**, avec un moteur simulé qui renvoie un doublon et une fin sans résultat final : le texte est accumulé sans doublon, marqué « non relue », et le provisoire est conservé.
- Dicter est bloqué hors connexion, avec son message ; Enregistrer reste disponible.
- Photo affichée. Ce test a révélé un bug de la version précédente, corrigé ici : les photos ne s'affichaient pas dans la fiche de visite.
- **Synchronisation** entrée par entrée vers KV, puis page admin : liste des visites, digest v2 réassemblé avec l'audio en base64.
- Carte, couches, tuiles et mode hors ligne : inchangés, revérifiés.
- **EXIF GPS** : `python3 rdc39/tests/test_exif_gps.py` (nécessite Pillow, piexif et node). 20 cas, relus avec Pillow :
  - JPEG d'entrée : sans EXIF, EXIF big-endian (Pillow, piexif), segment Exif vide façon Safari, EXIF little-endian ;
  - sorties en big-endian et en little-endian, hémisphères N/E et S/W, fuseaux + et − ;
  - vérifications : position à 1e-6° près, références, DateTimeOriginal et décalage, altitude et précision, un seul segment Exif, ancien EXIF retiré, pixels identiques ;
  - sans position, le fichier reste identique ; un fichier non JPEG n'est pas modifié.
- **Position**, testée de bout en bout dans le navigateur :
  - position refusée : fenêtre au premier lancement, statut « refusée », « ⚠ sans position » cliquable, photo exportée sans EXIF ;
  - position accordée : statut « OK ± 7 m », EXIF présent dans le digest, l'export standard et la synchro ;
  - position corrigée à la main : elle est reprise dans l'EXIF ;
  - signal GPS arrivé après la capture : la position est rattachée automatiquement.

## À tester sur téléphones réels

| Test | Appareils |
|---|---|
| Enregistrer en vrai mode avion (Wi-Fi coupé aussi), 2 à 3 min, puis réécoute. Sur iPhone : verrouiller l'écran pendant la capture, rouvrir, réécouter | Android + iPhone |
| Fermer brutalement l'app pendant un enregistrement, la rouvrir : l'« enregistrement récupéré » doit être relisible (en particulier le mp4 sur iPhone) | Android + iPhone |
| Dicter hors ligne : bouton bloqué avec explication | Android + iPhone |
| Dicter avec réseau, 60 à 90 s : ni doublons ni troncature. Un petit bip à chaque relance est possible sur certains Android | Android + iPhone |
| App qui se charge en mode avion, carte hors ligne avec tuiles préchargées | Les deux |
| Envoi interrompu puis repris sur réseau faible | Android |
| Révocation du code d'accès | Android |
