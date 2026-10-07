# Calepin Bureau

Outil local (Python) qui consolide les relevés de terrain de l'app **RDC39-Calepin**. Il lit les digests JSON (un fichier par visite, photos et audios encodés en base64) et produit :

| Sortie | Contenu |
|---|---|
| `releves.csv` | Une ligne par entrée, séparateur `;`, UTF-8 avec BOM (accents corrects dans Excel). |
| `releves.xlsx` | Feuilles `releves`, `visites` et `anomalies`. En-têtes figés, filtres, liens cliquables vers les photos, audios et pièces jointes. |
| `releves.geojson` | Un point par entrée positionnée, en WGS84, coordonnées `[lng, lat]`, avec tous les attributs en propriétés. |
| `photos/` | JPEG extraits **tels quels**, sans recompression (EXIF conservé), nommés `{visite}_{NN}_{repere}.jpg`. |
| `audio/` | Fichiers audio d'origine, sans conversion (`.webm` sur Android, `.m4a` sur iPhone). |
| `fichiers/` | Pièces jointes, nommées `{visite}_{NN}_{nom d'origine}`. |
| `rapport_import.txt` | Visites lues, doublons, corbeille, comptes par type, avertissements et liste des anomalies. |

**Confidentialité** : tout reste sur le PC. L'outil n'ouvre aucune connexion réseau. Il ne modifie jamais les fichiers d'entrée et refuse d'écrire dans un dossier `samples/`.

## Installation sous Windows

1. Installer Python 3.10 ou plus récent depuis <https://www.python.org/downloads/windows/>. Cocher **« Add python.exe to PATH »** à l'installation.
2. Ouvrir **PowerShell** dans le dossier `bureau` (dans l'Explorateur : Maj + clic droit > « Ouvrir dans le terminal »), puis :

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e .[test]
   ```

   Si PowerShell refuse d'activer l'environnement, lancer une fois `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
   Le paquet `tzdata` est installé automatiquement sous Windows : il fournit les fuseaux horaires (`Africa/Kigali`…).
3. Vérifier : `calepin-bureau --help`

À chaque nouvelle session PowerShell, réactiver l'environnement avec `.venv\Scripts\Activate.ps1`.

**Chemins longs** : l'outil gère les chemins Windows de plus de 260 caractères, et chaque nom de fichier extrait fait au plus 120 caractères. Pour ouvrir ces fichiers depuis d'autres logiciels, il reste préférable de choisir un dossier de sortie court, par exemple `C:\RDC39\sortie`.

### ffmpeg (facultatif)

ffmpeg sert à un seul contrôle : repérer les audios quasi silencieux (volume moyen inférieur à -60 dB). Sans ffmpeg, ce contrôle est ignoré et un avertissement le signale dans la console et dans `rapport_import.txt`. Tout le reste fonctionne.

Pour l'installer :
- `winget install Gyan.FFmpeg` (puis rouvrir PowerShell) ;
- ou télécharger une version « essentials » sur <https://www.gyan.dev/ffmpeg/builds/>, la décompresser, puis indiquer le chemin dans `config.yaml` : `ffmpeg: "C:\\outils\\ffmpeg\\bin\\ffmpeg.exe"`.

## Utilisation

```powershell
calepin-bureau importer <dossier_ou_zip> --sortie <dossier> [--fuseau Africa/Kigali] [--inclure-corbeille] [--config config.yaml]
```

Exemples :

```powershell
# Dossier de digests *.json (les sous-dossiers et les *.zip qu'il contient sont lus aussi)
calepin-bureau importer samples --sortie sortie

# ZIP d'export groupé de l'app (digests + index.json)
calepin-bureau importer "C:\Téléchargements\RDC39_export_2026-10-06_1830_5-visites.zip" --sortie C:\RDC39\sortie

# Heures locales dans un autre fuseau, visites en corbeille incluses
calepin-bureau importer samples --sortie sortie --fuseau Africa/Kinshasa --inclure-corbeille

# Sans installer la commande
python -m calepin_bureau importer samples --sortie sortie
```

**Relancer l'import** réécrit entièrement la sortie : `photos/`, `audio/`, `fichiers/` et les quatre fichiers de résultat sont supprimés puis recréés. Par sécurité, l'outil refuse un dossier de sortie non vide qu'il n'a pas créé lui-même (il le reconnaît au fichier `.calepin-bureau`), un dossier situé dans la source, et tout dossier `samples`. Fermer `releves.xlsx` dans Excel avant de relancer.

## Configuration : `config.yaml`

Le fichier est lu dans le dossier courant, ou à l'endroit indiqué par `--config`. Une clé absente reprend sa valeur par défaut.

| Clé | Défaut | Rôle |
|---|---|---|
| `fuseau` | `Africa/Kigali` | Fuseau des heures locales (`--fuseau` a priorité). |
| `themes` | FONC, OCC, SOC, ACC, HYD, RIV, TRAV, ERO, EMP, ACT | Codes de thème reconnus. Liste à compléter librement. |
| `theme_defaut` | `AUTRE` | Thème d'un repère dont le préfixe n'est pas dans la liste. |
| `precision_max_m` | `50` | Seuil au-delà duquel la précision GPS est signalée. |
| `audio_silence_db` | `-60` | Seuil du contrôle « audio quasi silencieux ». |
| `ffmpeg` | vide | Chemin de `ffmpeg.exe`. Vide : recherche dans le PATH. |
| `longueur_nom_max` | `120` | Longueur maximale des noms de fichiers extraits. |
| `csv_separateur` | `;` | Séparateur du CSV. Les nombres gardent le point décimal. |

## Règles appliquées

- **Thème** : préfixe du repère avant le premier espace ou tiret (`-`, `–`, `—`), sans tenir compte de la casse, ni d'un `:` ou d'un `.` final. Exemples : `FONC 12` et `fonc-12` donnent `FONC`, `ACT: marché` donne `ACT`. `FONC12` et `FONCIER 1` donnent `AUTRE`.
- **Heures** : `date_heure_utc` reprend l'horodatage du digest (UTC). `date_heure_locale` est convertie dans le fuseau choisi ; dans Excel, c'est une vraie date, filtrable.
- **Doublons** (même `uid` dans plusieurs digests, par exemple un JSON isolé et le même dans un ZIP) : la version au `genereLe` le plus récent est gardée, les autres sont écartées. Le choix est signalé ; à égalité, l'avertissement le précise.
- **Corbeille** : une visite dont `corbeille` est renseigné est exclue, sauf avec `--inclure-corbeille`. Elle figure tout de même dans la feuille `visites`, avec son statut.
- **Source du texte** (`source_texte`) : `dictee` si l'entrée porte `source: "dictee"` ; `transcrit` pour un audio qui a un texte ; sinon `saisi`. Vide s'il n'y a pas de texte.
- **position_ok** = `oui` si la position existe, que ses coordonnées sont valides et que la précision est connue et inférieure ou égale au seuil.
- **Colonnes ajoutées** en fin de tableau : `position_motif` (motif d'absence de position fourni par l'app) et `gps_releve_utc` (heure du relevé GPS, `fixTs`).
- **Ne jamais deviner** : un champ attendu mais absent est signalé (`CHAMP_MANQUANT`) et la cellule reste vide. L'ancien format (schéma 1, Calepin personnel) est lu avec un avertissement ; ses entrées n'ont pas d'`id`, la colonne reste donc vide. L'altitude, facultative dans l'app, n'est pas signalée quand elle manque.

### Anomalies signalées

Chaque anomalie figure dans la feuille `anomalies` (gravité, code, message, visite, entrée), dans la colonne `anomalie` de l'entrée et dans `rapport_import.txt`.

| Code | Gravité | Cas |
|---|---|---|
| `POSITION_ABSENTE` | attention | Position nulle, avec le motif (`refusee`, `indisponible`, `delai_depasse`, `non_supportee`) s'il est fourni. |
| `PRECISION_FAIBLE` | attention | Précision supérieure au seuil. |
| `PRECISION_INCONNUE` / `PRECISION_NULLE` | attention / info | Précision absente, ou égale à 0. |
| `POSITION_INVALIDE` | erreur | Coordonnées hors bornes, non numériques ou égales à 0, 0. |
| `PHOTO_SANS_EXIF_GPS` | attention | Le JPEG extrait n'a pas d'EXIF GPS alors que l'entrée a une position. |
| `PIECE_ILLISIBLE` | erreur | Champ `erreur` de l'app, média absent, base64 invalide, image non décodable, audio illisible par ffmpeg. |
| `SANS_REPERE` | attention | Entrée sans repère. |
| `AUDIO_SILENCIEUX` | attention | Volume moyen inférieur au seuil (avec ffmpeg). |
| `DOUBLON_GARDE` / `DOUBLON_ECARTE` | attention / info | Même `uid` dans plusieurs digests. |
| `CORBEILLE_EXCLUE` / `CORBEILLE_INCLUSE` | info | Visite en corbeille. |
| `SCHEMA_1`, `SCHEMA_INCONNU` | attention | Ancien format, ou version de schéma inconnue. |
| `CHAMP_MANQUANT`, `UID_ABSENT`, `HORODATAGE_INVALIDE`, `TYPE_INCONNU` | erreur / attention | Champ attendu absent ou illisible. |
| `ENTREES_MANQUANTES`, `SUPPRIMEE_SUR_TELEPHONE`, `ENREGISTREMENT_RECUPERE` | erreur / attention / info | Informations ajoutées par le relais ou l'app. |
| `INDEX_STATUT`, `INDEX_FICHIER_ABSENT` | erreur / attention | `index.json` d'un export groupé : visite `vide`, `partiel` ou `erreur`, ou fichier annoncé absent du ZIP. |
| `FICHIER_ILLISIBLE`, `FICHIER_IGNORE` | erreur / info | JSON ou ZIP illisible, ou JSON qui n'est pas un digest. |

## Tests

```powershell
pip install -e .[test]
pytest
```

- `tests/test_import.py` utilise un jeu synthétique construit d'après le code de l'app (`rdc39/index.html` : `entryToDigest`, `buildDigest`, export groupé ; `index.html` pour le schéma 1). Il couvre les doublons, la corbeille, la position nulle, les pièces illisibles, les codes de thème, l'EXIF, les audios silencieux, le ZIP avec `index.json` et l'idempotence.
- `tests/test_samples_reels.py` tourne sur les vrais digests de `samples/`, cherchés dans `bureau/samples/` puis à la racine du dépôt, ou désignés par la variable `CALEPIN_SAMPLES`. Il recalcule les attendus depuis les JSON bruts et vérifie que `samples/` n'est pas modifié. Il est ignoré si le dossier est absent. `samples/` n'est jamais versionné (`.gitignore`).

## Hors périmètre (étapes suivantes)

Transcription des audios, rapports Word, relais, interface web, base de données.
