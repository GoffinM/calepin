"""Consolidation : visites retenues, lignes de relevés, anomalies, extraction des médias."""
from __future__ import annotations

import base64
import binascii
import math
import os
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import medias
from .config import Config
from .lecture import DigestLu, Lecture
from .noms import assainir, chemin_os, nom_media

TYPES_CONNUS = ("photo", "audio", "texte", "point", "fichier")
MOTIFS_POSITION = {
    "refusee": "autorisation refusée",
    "indisponible": "position indisponible",
    "delai_depasse": "délai GPS dépassé",
    "non_supportee": "géolocalisation non prise en charge",
}
CHAMPS_VISITE = {
    1: ("uid", "category", "tag", "date", "entries"),
    2: ("schemaVersion", "uid", "tag", "date", "dossier", "tags", "corbeille", "appareil", "versionApp",
        "genereLe", "entries"),
}
CHAMPS_ENTREE = {
    1: ("type", "horodatage", "repere", "position"),
    2: ("id", "type", "horodatage", "repere", "position", "texte"),
}

COLONNES_RELEVES = [
    "visite_uid", "visite_nom", "appareil", "version_app", "entree_id", "type",
    "date_heure_locale", "date_heure_utc", "theme", "repere", "lat", "lng", "precision_m", "altitude_m",
    "position_ok", "anomalie", "texte", "source_texte", "fichier_photo", "fichier_audio", "duree_audio_s",
    "fichier_joint",
    # Compléments : motif d'absence de position et heure du relevé GPS (versions récentes de l'app).
    "position_motif", "gps_releve_utc",
]
COLONNES_VISITES = [
    "visite_uid", "visite_nom", "statut", "date_locale", "date_utc", "dossier", "tags", "schema",
    "appareil", "version_app", "genere_le_utc", "corbeille_utc", "fichier_source", "nb_entrees",
    "nb_photo", "nb_audio", "nb_texte", "nb_point", "nb_fichier", "nb_autre", "nb_anomalies",
    "entrees_manquantes",
]
COLONNES_ANOMALIES = ["gravite", "code", "message", "visite_uid", "visite_nom", "entree_id", "type",
                      "repere", "fichier_source"]

STATUT_IMPORTEE = "importée"
STATUT_DOUBLON = "doublon écarté"
STATUT_CORBEILLE = "corbeille, exclue"


@dataclass
class Anomalie:
    gravite: str        # erreur | attention | info
    code: str
    message: str
    visite_uid: str = ""
    visite_nom: str = ""
    entree_id: str = ""
    type: str = ""
    repere: str = ""
    fichier_source: str = ""

    def ligne(self) -> dict:
        return {c: getattr(self, c) for c in COLONNES_ANOMALIES}


@dataclass
class Visite:
    digest: DigestLu
    schema: int | None
    uid: str
    nom: str
    statut: str = STATUT_IMPORTEE
    libelle_fichier: str = ""
    lignes: list[dict] = field(default_factory=list)
    anomalies: list[Anomalie] = field(default_factory=list)

    @property
    def d(self) -> dict:
        return self.digest.donnees


@dataclass
class Resultat:
    visites: list[Visite] = field(default_factory=list)
    anomalies_import: list[Anomalie] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    fichiers_ecrits: list[str] = field(default_factory=list)
    nb_digests_lus: int = 0

    @property
    def retenues(self) -> list[Visite]:
        return [v for v in self.visites if v.statut == STATUT_IMPORTEE]

    @property
    def lignes(self) -> list[dict]:
        return [l for v in self.retenues for l in v.lignes]

    @property
    def anomalies(self) -> list[Anomalie]:
        return self.anomalies_import + [a for v in self.visites for a in v.anomalies]


# ---------------------------------------------------------------- utilitaires

def parse_iso(valeur) -> datetime | None:
    """ISO 8601 (« Z » accepté) -> datetime UTC ; None si absent ou invalide."""
    if not isinstance(valeur, str) or not valeur.strip():
        return None
    s = valeur.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:       # sans fuseau : on ne devine pas
        return None
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def theme_de(repere: str | None, config: Config) -> str:
    """Préfixe du repère (avant le premier espace ou tiret), s'il figure dans la liste des codes."""
    if not repere or not repere.strip():
        return config.theme_defaut
    prefixe = re.split(r"[\s\-‐‑‒–—]", repere.strip(), maxsplit=1)[0]
    prefixe = prefixe.strip(".:;,").upper()
    return prefixe if prefixe in config.themes else config.theme_defaut


def _nombre(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _b64(valeur) -> bytes | None:
    if not isinstance(valeur, str) or not valeur:
        return None
    try:
        return base64.b64decode(valeur, validate=True)
    except (binascii.Error, ValueError):
        try:   # base64 avec retours à la ligne ou sans remplissage
            return base64.b64decode(re.sub(r"\s+", "", valeur) + "===")
        except (binascii.Error, ValueError):
            return None


# ---------------------------------------------------------------- sélection des visites

def _schema(d: dict) -> int | None:
    v = d.get("schemaVersion")
    if v in (1, 2):
        return v
    if v is None and "category" in d:       # le Calepin personnel v1 porte toujours schemaVersion,
        return 1                            # mais on accepte un v1 qui l'aurait perdu
    return None


def selectionner(lecture: Lecture, inclure_corbeille: bool, res: Resultat) -> None:
    """Crée les Visite, écarte doublons (garde le genereLe le plus récent) et corbeille."""
    for source, raison in lecture.illisibles:
        res.anomalies_import.append(Anomalie("erreur", "FICHIER_ILLISIBLE", raison, fichier_source=source))
    for source, raison in lecture.ignores:
        res.anomalies_import.append(Anomalie("info", "FICHIER_IGNORE", raison, fichier_source=source))

    for dl in lecture.digests:
        d = dl.donnees
        schema = _schema(d)
        uid = d.get("uid") if isinstance(d.get("uid"), str) else ""
        nom = d.get("tag").strip() if isinstance(d.get("tag"), str) else ""
        v = Visite(dl, schema, uid, nom)
        a = lambda grav, code, msg: v.anomalies.append(
            Anomalie(grav, code, msg, visite_uid=uid, visite_nom=nom, fichier_source=dl.source))
        if schema is None:
            a("attention", "SCHEMA_INCONNU",
              f"schemaVersion = {d.get('schemaVersion')!r} : lu comme le schéma 2, sans garantie")
        elif schema == 1:
            a("attention", "SCHEMA_1", "ancien format (Calepin personnel, schéma 1) : pas d'id d'entrée, "
              "pas d'audio, ni appareil ni version d'app")
        attendus = CHAMPS_VISITE[schema or 2]
        manquants = [c for c in attendus if c not in d]
        if manquants:
            a("erreur", "CHAMP_MANQUANT", "champ(s) absent(s) de la visite : " + ", ".join(manquants))
        if not uid:
            a("erreur", "UID_ABSENT", "visite sans uid : impossible de détecter un doublon")
        if not nom:
            a("info", "VISITE_SANS_NOM", "visite sans nom (tag vide) : fichiers nommés d'après l'uid")
        manq = d.get("entreesManquantes")
        if isinstance(manq, list) and manq:
            a("erreur", "ENTREES_MANQUANTES",
              f"{len(manq)} entrée(s) annoncée(s) mais absente(s) du digest : {', '.join(map(str, manq))}")
        if not d.get("entries"):
            a("attention", "VISITE_VIDE", "visite sans aucune entrée")
        res.visites.append(v)

    # Doublons : même uid dans plusieurs digests -> garder le genereLe le plus récent.
    par_uid: dict[str, list[Visite]] = {}
    for v in res.visites:
        if v.uid:
            par_uid.setdefault(v.uid, []).append(v)
    for uid, groupe in par_uid.items():
        if len(groupe) < 2:
            continue
        cle = lambda v: parse_iso(v.d.get("genereLe")) or datetime.min.replace(tzinfo=timezone.utc)
        gardee = max(groupe, key=cle)      # à égalité : le premier lu (ordre alphabétique des sources)
        egalite = sum(1 for v in groupe if cle(v) == cle(gardee)) > 1
        for v in groupe:
            if v is gardee:
                autres = ", ".join(x.digest.source for x in groupe if x is not v)
                msg = f"uid présent dans {len(groupe)} digests ; version gardée (genereLe " \
                      f"{v.d.get('genereLe') or 'absent'}) ; écartée(s) : {autres}"
                if egalite:
                    msg += " ; ATTENTION : genereLe identique ou absent, choix par ordre de lecture"
                v.anomalies.append(Anomalie("attention", "DOUBLON_GARDE", msg, visite_uid=uid,
                                            visite_nom=v.nom, fichier_source=v.digest.source))
            else:
                v.statut = STATUT_DOUBLON
                v.anomalies.append(Anomalie(
                    "info", "DOUBLON_ECARTE",
                    f"doublon écarté (genereLe {v.d.get('genereLe') or 'absent'}), remplacé par "
                    f"{gardee.digest.source}", visite_uid=uid, visite_nom=v.nom, fichier_source=v.digest.source))

    for v in res.visites:
        if v.statut == STATUT_IMPORTEE and v.d.get("corbeille"):
            if inclure_corbeille:
                v.anomalies.append(Anomalie("info", "CORBEILLE_INCLUSE",
                                            f"visite en corbeille ({v.d.get('corbeille')}), incluse "
                                            "(--inclure-corbeille)", visite_uid=v.uid, visite_nom=v.nom,
                                            fichier_source=v.digest.source))
            else:
                v.statut = STATUT_CORBEILLE
                v.anomalies.append(Anomalie("info", "CORBEILLE_EXCLUE",
                                            f"visite en corbeille ({v.d.get('corbeille')}), exclue "
                                            "(voir --inclure-corbeille)", visite_uid=v.uid, visite_nom=v.nom,
                                            fichier_source=v.digest.source))

    # index.json des exports groupés : statuts signalés par l'app, fichiers annoncés mais absents.
    sources = {dl.source for dl in lecture.digests} | {s for s, _ in lecture.illisibles}
    for source, index in lecture.index:
        conteneur, _, interne = source.rpartition("!")
        dossier = posixpath.dirname(interne)
        prefixe = (conteneur + "!" if conteneur else "") + (dossier + "/" if dossier else "")
        for ligne in index.get("visites") or []:
            if not isinstance(ligne, dict):
                continue
            statut = ligne.get("statut")
            base = dict(visite_uid=str(ligne.get("uid") or ""), visite_nom=str(ligne.get("repere") or ""),
                        fichier_source=source)
            if statut and statut != "ok":
                details = ligne.get("erreur") or "; ".join(
                    f"{e.get('type')} {e.get('id')} : {e.get('erreur')}" for e in ligne.get("entreesEnErreur") or [])
                res.anomalies_import.append(Anomalie(
                    "erreur" if statut == "erreur" else "attention", "INDEX_STATUT",
                    f"index.json : statut « {statut} »" + (f" ({details})" if details else ""), **base))
            fichier = ligne.get("fichier")
            if fichier and prefixe + fichier not in sources:
                res.anomalies_import.append(Anomalie(
                    "erreur", "INDEX_FICHIER_ABSENT", f"index.json annonce {fichier}, absent de l'archive", **base))

    # Libellé de fichier unique par visite retenue (même nom de visite -> suffixe uid).
    retenues = [v for v in res.visites if v.statut == STATUT_IMPORTEE]
    for v in retenues:
        v.libelle_fichier = assainir(v.nom, defaut="visite-" + assainir(v.uid[:8], "sans-uid"), longueur_max=40)
    compte = Counter(v.libelle_fichier for v in retenues)
    for v in retenues:
        if compte[v.libelle_fichier] > 1:
            suffixe = assainir(v.uid[:8], "sans-uid")
            v.libelle_fichier = f"{v.libelle_fichier[:31]}-{suffixe}"
    compte = Counter(v.libelle_fichier for v in retenues)
    vus: Counter = Counter()
    for v in retenues:      # derniers cas (uid identiques ou absents)
        if compte[v.libelle_fichier] > 1:
            vus[v.libelle_fichier] += 1
            v.libelle_fichier = f"{v.libelle_fichier}-{vus[v.libelle_fichier]}"


# ---------------------------------------------------------------- entrées

class Extracteur:
    """Écrit les médias dans photos/, audio/ et fichiers/ et contrôle ce qui a été écrit."""

    def __init__(self, sortie: Path, config: Config, res: Resultat):
        self.sortie = sortie
        self.config = config
        self.res = res
        self.ffmpeg = medias.trouver_ffmpeg(config.ffmpeg)
        self.noms_pris: set[str] = set()
        if not self.ffmpeg:
            res.avertissements.append(
                "ffmpeg introuvable : contrôle des audios quasi silencieux ignoré"
                + (f" (chemin configuré : {config.ffmpeg})" if config.ffmpeg else " (installer ffmpeg ou "
                   "renseigner « ffmpeg » dans config.yaml)"))

    def ecrire(self, sous_dossier: str, nom: str, octets: bytes) -> tuple[str, Path]:
        base, point, ext = nom.rpartition(".")
        if not point:
            base, ext = nom, ""
        candidat, n = nom, 1
        while (sous_dossier + "/" + candidat).lower() in self.noms_pris:   # Windows : casse ignorée
            n += 1
            candidat = f"{base}-{n}.{ext}" if ext else f"{base}-{n}"
        relatif = f"{sous_dossier}/{candidat}"
        self.noms_pris.add(relatif.lower())
        chemin = self.sortie / sous_dossier / candidat
        os.makedirs(chemin_os(chemin.parent), exist_ok=True)
        with open(chemin_os(chemin), "wb") as f:
            f.write(octets)
        self.res.fichiers_ecrits.append(relatif)
        return relatif, chemin


def traiter_visite(v: Visite, config: Config, fuseau: ZoneInfo, ext: Extracteur) -> None:
    d = v.d
    schema = v.schema or 2
    entrees = d.get("entries") or []
    largeur = max(2, len(str(len(entrees))))
    appareil = d.get("appareil") if isinstance(d.get("appareil"), str) else ""
    version = d.get("versionApp") if isinstance(d.get("versionApp"), str) else ""

    for rang, e in enumerate(entrees, start=1):
        if not isinstance(e, dict):
            v.anomalies.append(Anomalie("erreur", "ENTREE_ILLISIBLE", f"entrée n° {rang} : pas un objet JSON",
                                        visite_uid=v.uid, visite_nom=v.nom, fichier_source=v.digest.source))
            continue
        anomalies: list[Anomalie] = []
        type_ = e.get("type") if isinstance(e.get("type"), str) else ""
        repere = e.get("repere").strip() if isinstance(e.get("repere"), str) else ""
        entree_id = str(e.get("id")) if e.get("id") not in (None, "") else ""

        def signaler(grav: str, code: str, msg: str) -> None:
            anomalies.append(Anomalie(grav, code, msg, visite_uid=v.uid, visite_nom=v.nom,
                                      entree_id=entree_id or f"n° {rang}", type=type_, repere=repere,
                                      fichier_source=v.digest.source))

        manquants = [c for c in CHAMPS_ENTREE[schema] if c not in e]
        if manquants:
            signaler("erreur", "CHAMP_MANQUANT", "champ(s) absent(s) : " + ", ".join(manquants))
        if type_ and type_ not in TYPES_CONNUS:
            signaler("attention", "TYPE_INCONNU", f"type d'entrée inconnu : {type_!r}")
        if not repere:
            signaler("attention", "SANS_REPERE", "entrée sans repère")
        if e.get("recupere"):
            signaler("info", "ENREGISTREMENT_RECUPERE", "enregistrement récupéré après interruption")
        if e.get("supprimeeSurTelephone"):
            signaler("attention", "SUPPRIMEE_SUR_TELEPHONE",
                     "entrée supprimée sur le téléphone après envoi (conservée par le relais)")

        # Horodatage
        horo = parse_iso(e.get("horodatage"))
        if horo is None and "horodatage" in e:
            signaler("erreur", "HORODATAGE_INVALIDE", f"horodatage absent ou illisible : {e.get('horodatage')!r}")

        # Position
        pos = e.get("position")
        lat = lng = precision = altitude = None
        fix = None
        position_ok = False
        motif = e.get("positionMotif") if isinstance(e.get("positionMotif"), str) else ""
        if isinstance(pos, dict):
            lat, lng = _nombre(pos.get("lat")), _nombre(pos.get("lng"))
            precision, altitude = _nombre(pos.get("accuracy")), _nombre(pos.get("altitude"))
            fix = parse_iso(pos.get("fixTs"))
            if lat is None or lng is None or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                signaler("erreur", "POSITION_INVALIDE",
                         f"coordonnées invalides : lat={pos.get('lat')!r}, lng={pos.get('lng')!r}")
                lat = lng = None
            elif lat == 0 and lng == 0:
                signaler("erreur", "POSITION_INVALIDE", "coordonnées 0, 0 (position non renseignée)")
                lat = lng = None
            else:
                if precision is None:
                    signaler("attention", "PRECISION_INCONNUE",
                             "précision absente" + ("" if "fixTs" in pos else " (pas de fixTs : saisie manuelle "
                                                    "ou ancienne version)"))
                elif precision > config.precision_max_m:
                    signaler("attention", "PRECISION_FAIBLE",
                             f"précision {precision:g} m > seuil {config.precision_max_m:g} m")
                elif precision == 0:
                    signaler("info", "PRECISION_NULLE", "précision de 0 m : valeur sans doute non fournie par "
                             "l'appareil")
                position_ok = precision is not None and 0 < precision <= config.precision_max_m
            if "fixTs" in pos and fix is None:
                signaler("attention", "FIXTS_INVALIDE", f"fixTs illisible : {pos.get('fixTs')!r}")
        elif pos is not None:
            signaler("erreur", "POSITION_INVALIDE", f"position illisible : {pos!r}")
        else:
            libelle = MOTIFS_POSITION.get(motif, motif) if motif else ""
            signaler("attention", "POSITION_ABSENTE",
                     "position absente" + (f" (motif : {libelle})" if libelle else " (motif non renseigné)"))

        # Texte
        texte = e.get("texte") if isinstance(e.get("texte"), str) else ""
        source_texte = ""
        if texte.strip():
            if e.get("source") == "dictee":
                source_texte = "dictee"
            elif type_ == "audio":
                source_texte = "transcrit"
            else:
                source_texte = "saisi"
        elif type_ == "texte":
            signaler("attention", "TEXTE_VIDE", "note texte vide")

        if e.get("erreur"):
            signaler("erreur", "PIECE_ILLISIBLE", f"signalée par l'app : {e.get('erreur')}")

        numero = str(rang).zfill(largeur)
        libelle_repere = assainir(repere, defaut="sans-repere", longueur_max=80)
        fichier_photo = fichier_audio = fichier_joint = ""
        duree = None

        if type_ == "photo":
            img = e.get("image")
            octets = _b64(img.get("base64")) if isinstance(img, dict) else None
            if octets is None:
                if not e.get("erreur"):
                    signaler("erreur", "PIECE_ILLISIBLE", "photo absente ou base64 illisible")
            else:
                jpeg = medias.est_jpeg(octets)
                extension = ".jpg" if jpeg else medias.extension_pour(img.get("mime"), ".bin")
                if not jpeg:
                    signaler("attention", "PHOTO_NON_JPEG", f"photo non JPEG (mime {img.get('mime')!r})")
                nom = nom_media(v.libelle_fichier, numero, libelle_repere, extension, config.longueur_nom_max)
                fichier_photo, chemin = ext.ecrire("photos", nom, octets)
                lisible, a_gps, err = medias.controler_photo(chemin)
                if not lisible:
                    signaler("erreur", "PIECE_ILLISIBLE", f"photo extraite illisible : {err}")
                elif jpeg and lat is not None and not a_gps:
                    signaler("attention", "PHOTO_SANS_EXIF_GPS", "photo sans EXIF GPS alors que la position existe")

        elif type_ == "audio":
            au = e.get("audio")
            duree = _nombre(au.get("duree")) if isinstance(au, dict) else None
            octets = _b64(au.get("base64")) if isinstance(au, dict) else None
            if octets is None:
                if schema == 1 and not isinstance(au, dict):
                    pass        # le schéma 1 n'exporte jamais l'audio : ce n'est pas une anomalie
                elif not e.get("erreur"):
                    signaler("erreur", "PIECE_ILLISIBLE", "audio absent ou base64 illisible")
            else:
                if duree is None:
                    signaler("attention", "DUREE_ABSENTE", "durée audio absente")
                extension = medias.extension_pour(au.get("mime"), ".bin")
                nom = nom_media(v.libelle_fichier, numero, libelle_repere, extension, config.longueur_nom_max)
                fichier_audio, chemin = ext.ecrire("audio", nom, octets)
                if ext.ffmpeg:
                    db, err = medias.volume_moyen_db(ext.ffmpeg, chemin)
                    if err:
                        signaler("erreur", "PIECE_ILLISIBLE", f"audio : {err}")
                    elif db < config.audio_silence_db:
                        signaler("attention", "AUDIO_SILENCIEUX",
                                 f"audio quasi silencieux : volume moyen {db:.1f} dB < {config.audio_silence_db:g} dB")

        elif type_ == "fichier":
            fi = e.get("fichier")
            octets = _b64(fi.get("base64")) if isinstance(fi, dict) else None
            if octets is None:
                if not e.get("erreur"):
                    signaler("erreur", "PIECE_ILLISIBLE", "pièce jointe absente ou base64 illisible")
            else:
                nom_origine = fi.get("nom") if isinstance(fi.get("nom"), str) else ""
                if not nom_origine:
                    signaler("info", "NOM_FICHIER_ABSENT", "pièce jointe sans nom d'origine")
                racine, point, suffixe = nom_origine.rpartition(".")
                if point and racine and 1 <= len(suffixe) <= 8:
                    extension = "." + assainir(suffixe, "bin", 8).lower()
                    libelle = assainir(racine, defaut=libelle_repere, longueur_max=80)
                else:
                    extension = medias.extension_pour(fi.get("mime"), ".bin")
                    libelle = assainir(nom_origine, defaut=libelle_repere, longueur_max=80)
                nom = nom_media(v.libelle_fichier, numero, libelle, extension, config.longueur_nom_max)
                fichier_joint, _ = ext.ecrire("fichiers", nom, octets)

        v.anomalies.extend(anomalies)
        v.lignes.append({
            "visite_uid": v.uid,
            "visite_nom": v.nom,
            "appareil": appareil,
            "version_app": version,
            "entree_id": entree_id,
            "type": type_,
            "date_heure_locale": horo.astimezone(fuseau).replace(tzinfo=None) if horo else None,
            "date_heure_utc": iso_utc(horo),
            "theme": theme_de(repere, config),
            "repere": repere,
            "lat": lat,
            "lng": lng,
            "precision_m": precision if lat is not None else None,
            "altitude_m": altitude if lat is not None else None,
            "position_ok": "oui" if position_ok else "non",
            "anomalie": " ; ".join(f"{a.code} : {a.message}" for a in anomalies),
            "texte": texte,
            "source_texte": source_texte,
            "fichier_photo": fichier_photo,
            "fichier_audio": fichier_audio,
            "duree_audio_s": duree,
            "fichier_joint": fichier_joint,
            "position_motif": motif if pos is None else "",
            "gps_releve_utc": iso_utc(fix),
        })


def ligne_visite(v: Visite, fuseau: ZoneInfo) -> dict:
    d = v.d
    date = parse_iso(d.get("date"))
    types = Counter(l["type"] for l in v.lignes) if v.lignes else Counter(
        e.get("type") for e in d.get("entries") or [] if isinstance(e, dict))
    tags = d.get("tags")
    manq = d.get("entreesManquantes")
    return {
        "visite_uid": v.uid,
        "visite_nom": v.nom,
        "statut": v.statut,
        "date_locale": date.astimezone(fuseau).replace(tzinfo=None) if date else None,
        "date_utc": iso_utc(date) or (str(d.get("date")) if d.get("date") else ""),
        "dossier": d.get("dossier") or "",
        "tags": ", ".join(map(str, tags)) if isinstance(tags, list) else "",
        "schema": v.schema if v.schema else str(d.get("schemaVersion")),
        "appareil": d.get("appareil") or "",
        "version_app": d.get("versionApp") or "",
        "genere_le_utc": iso_utc(parse_iso(d.get("genereLe"))),
        "corbeille_utc": iso_utc(parse_iso(d.get("corbeille"))) or (str(d["corbeille"]) if d.get("corbeille") else ""),
        "fichier_source": v.digest.source,
        "nb_entrees": len(d.get("entries") or []),
        "nb_photo": types.get("photo", 0),
        "nb_audio": types.get("audio", 0),
        "nb_texte": types.get("texte", 0),
        "nb_point": types.get("point", 0),
        "nb_fichier": types.get("fichier", 0),
        "nb_autre": sum(n for t, n in types.items() if t not in TYPES_CONNUS),
        "nb_anomalies": len(v.anomalies),
        "entrees_manquantes": len(manq) if isinstance(manq, list) else 0,
    }
