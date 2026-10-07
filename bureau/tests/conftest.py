"""Jeux de test.

1. `samples/` réels (dossier non versionné) : cherchés dans bureau/samples, puis à la racine du dépôt,
   ou désignés par la variable CALEPIN_SAMPLES. Les tests qui en dépendent sont ignorés s'ils sont absents.
2. Jeu synthétique construit selon le code de l'app (rdc39/index.html : entryToDigest, buildManifest,
   buildDigest, export groupé ; index.html : digest v1) : il couvre les cas limites précis.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

ICI = Path(__file__).resolve().parent


def dossier_samples() -> Path | None:
    candidats = [os.environ.get("CALEPIN_SAMPLES"), ICI.parent / "samples", ICI.parent.parent / "samples"]
    for c in candidats:
        if c and Path(c).is_dir() and any(p.suffix.lower() in (".json", ".zip") for p in Path(c).rglob("*")):
            return Path(c)
    return None


def b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode()


def jpeg(gps: bool, couleur=(200, 120, 40)) -> bytes:
    img = Image.new("RGB", (32, 24), couleur)
    buf = io.BytesIO()
    if gps:
        ex = Image.Exif()
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "S", (1.0, 57.0, 12.5), "E", (30.0, 3.0, 40.0)
        img.save(buf, "JPEG", quality=85, exif=ex.tobytes())
    else:
        img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def audio_webm(silence: bool) -> bytes:
    """2 s d'opus/webm généré par ffmpeg ; à défaut, octets arbitraires (contrôle de volume alors ignoré)."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return b"\x1aE\xdf\xa3" + (b"\x00" if silence else b"\x01") * 64
    src = "anullsrc=r=48000:cl=mono" if silence else "sine=frequency=440:sample_rate=48000"
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src, "-t", "2",
                        "-c:a", "libopus", "-f", "webm", "-"], capture_output=True, check=True)
    return r.stdout


POS_BONNE = {"lat": -1.954210, "lng": 30.061230, "accuracy": 6, "fixTs": "2026-10-05T08:00:01.000Z"}


def entree(id_, type_, heure, repere, position=POS_BONNE, texte=None, **extra):
    e = {"id": id_, "type": type_, "horodatage": f"2026-10-05T{heure}.000Z", "repere": repere,
         "position": position, "texte": texte}
    if position is None:
        e["positionMotif"] = extra.pop("positionMotif", "indisponible")
    e.update(extra)
    return e


def visite_v2(uid, tag, entries, genere="2026-10-05T12:00:00.000Z", corbeille=None):
    return {"schemaVersion": 2, "uid": uid, "tag": tag, "date": "2026-10-05T07:30:00.000Z", "dossier": "Mission",
            "tags": ["rive"], "corbeille": corbeille, "appareil": "android-ab12", "versionApp": "rdc39-2026-10-06.2",
            "genereLe": genere, "syntheseBrute": tag + "\n", "entries": entries}


def construire_jeu(dossier: Path) -> dict:
    """Écrit le jeu synthétique ; renvoie les valeurs attendues."""
    dossier.mkdir(parents=True, exist_ok=True)
    photo_gps, photo_sans = jpeg(True), jpeg(False, (10, 200, 90))
    son, silence = audio_webm(False), audio_webm(True)
    a_entries = [
        entree("e01", "photo", "08:00:02", "FONC 12 borne", image={"mime": "image/jpeg", "base64": b64(photo_gps)}),
        entree("e02", "photo", "08:01:00", "hyd-3 ravine", image={"mime": "image/jpeg", "base64": b64(photo_sans)}),
        entree("e03", "photo", "08:02:00", "ERO 1", image=None, erreur="photo illisible : aucune donnée disponible"),
        entree("e04", "audio", "08:03:00", "SOC 2 entretien",
               audio={"mime": "audio/webm;codecs=opus", "base64": b64(son), "duree": 2}),
        entree("e05", "audio", "08:04:00", "SOC 3", texte="Transcription déjà faite.",
               audio={"mime": "audio/webm;codecs=opus", "base64": b64(silence), "duree": 2}),
        entree("e06", "texte", "08:05:00", "OCC–4 champ", texte="Note saisie : manioc, 2 ha"),
        entree("e07", "texte", "08:06:00", "TRAV 1", texte="Texte dicté non relu", source="dictee"),
        entree("e08", "point", "08:07:00", "RIV 5 pile de pont",
               position={"lat": -1.95, "lng": 30.06, "accuracy": 120, "altitude": 1510.4,
                         "fixTs": "2026-10-05T08:06:59.000Z"}),
        entree("e09", "point", "08:08:00", "ACC 7", position=None, positionMotif="refusee"),
        entree("e10", "fichier", "08:09:00", "EMP 2",
               fichier={"nom": "Plan d'emprise é.pdf", "mime": "application/pdf", "base64": b64(b"%PDF-1.4 test")}),
        entree("e11", "texte", "08:10:00", None, texte="Sans repère"),
        entree("e12", "texte", "08:11:00", "XYZ 9 inconnu", texte="Code inconnu"),
        entree("e13", "texte", "08:12:00", "act:1", texte="Préfixe collé (act:1)",
               position={"lat": -1.951, "lng": 30.062}),
    ]
    visite_a = visite_v2("uid-aaaa-1111", "Site Mbandaka – rive gauche", a_entries)
    visite_a_vieux = visite_v2("uid-aaaa-1111", "Site Mbandaka – rive gauche", a_entries[:2],
                               genere="2026-10-05T09:00:00.000Z")
    visite_b = visite_v2("uid-bbbb-2222", "Visite supprimée",
                         [entree("b01", "texte", "09:00:00", "FONC 1", texte="en corbeille")],
                         corbeille="2026-10-06T10:00:00.000Z")
    visite_c_v1 = {
        "schemaVersion": 1, "uid": "uid-cccc-3333", "category": "Immobilier", "tag": "", "date": "2025-03-02T10:00:00.000Z",
        "syntheseBrute": "—", "syntheseIA": None,
        "entries": [
            {"type": "photo", "horodatage": "2025-03-02T10:01:00.000Z", "repere": "Façade",
             "position": {"lat": 50.85, "lng": 4.35, "accuracy": 12}, "image": {"mime": "image/jpeg", "base64": b64(photo_gps)}},
            {"type": "audio", "horodatage": "2025-03-02T10:02:00.000Z", "repere": "Cuisine", "position": None,
             "texte": "Transcription v1"},
            {"type": "fichier", "horodatage": "2025-03-02T10:03:00.000Z", "repere": "Plan", "position": None,
             "fichier": None, "erreur": "fichier illisible : aucune donnée disponible"},
        ],
    }
    ecrire = lambda nom, d: (dossier / nom).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    ecrire("2026-10-05_Site_Mbandaka_uid-aaaa.json", visite_a)
    ecrire("ancien_Site_Mbandaka_digest.json", visite_a_vieux)
    ecrire("2026-10-05_Visite_supprimee_uid-bbbb.json", visite_b)
    ecrire("calepin_v1_digest.json", visite_c_v1)
    (dossier / "pas_un_digest.json").write_text('{"bonjour": 1}', encoding="utf-8")

    # ZIP d'export groupé (format de l'app : un digest par visite + index.json)
    index = {"schema": "rdc39-export-index", "schemaIndex": 1, "schemaDigest": 2, "app": "rdc39-2026-10-06.2",
             "genereLe": "2026-10-06T12:00:00.000Z", "appareil": "android-ab12", "partie": 1, "parties": 1,
             "visitesSelectionnees": 3,
             "visites": [
                 {"fichier": "2026-10-05_Site_Mbandaka_uid-aaaa.json", "uid": "uid-aaaa-1111",
                  "repere": visite_a["tag"], "entrees": 13, "taille": 1, "statut": "partiel",
                  "entreesEnErreur": [{"id": "e03", "type": "photo", "erreur": "photo illisible"}]},
                 {"fichier": "2026-10-05_Visite_supprimee_uid-bbbb.json", "uid": "uid-bbbb-2222",
                  "repere": "Visite supprimée", "entrees": 1, "taille": 1, "statut": "ok"},
                 {"fichier": None, "uid": "uid-dddd-4444", "repere": "Cassée", "entrees": 0, "statut": "erreur",
                  "erreur": "[RDC39] lecture impossible"},
             ], "visitesDansCeFichier": 3}
    zip_chemin = dossier.parent / (dossier.name + ".zip")
    with zipfile.ZipFile(zip_chemin, "w") as z:
        z.writestr("2026-10-05_Site_Mbandaka_uid-aaaa.json", json.dumps(visite_a, ensure_ascii=False))
        z.writestr("2026-10-05_Visite_supprimee_uid-bbbb.json", json.dumps(visite_b, ensure_ascii=False))
        z.writestr("index.json", json.dumps(index, ensure_ascii=False, indent=1))
    return {"photo_gps": photo_gps, "photo_sans": photo_sans, "son": son, "silence": silence, "zip": zip_chemin,
            "visite_a": visite_a}


@pytest.fixture(scope="session")
def jeu(tmp_path_factory):
    racine = tmp_path_factory.mktemp("jeu")
    attendu = construire_jeu(racine / "digests")
    attendu["dossier"] = racine / "digests"
    return attendu


@pytest.fixture(scope="session")
def import_jeu(jeu, tmp_path_factory):
    from calepin_bureau.config import Config
    from calepin_bureau.importer import importer
    sortie = tmp_path_factory.mktemp("sortie") / "sortie"
    res, rapport = importer(jeu["dossier"], sortie, Config())
    return res, rapport, sortie
