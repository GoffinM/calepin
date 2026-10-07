"""Tests sur les vrais digests de samples/ (ignorés si le dossier est absent).

Les valeurs attendues sont recalculées depuis les JSON bruts, indépendamment du code testé.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from calepin_bureau.config import Config
from calepin_bureau.importer import importer

from conftest import dossier_samples

SAMPLES = dossier_samples()
pytestmark = pytest.mark.skipif(SAMPLES is None, reason="dossier samples/ absent (non versionné)")


def digests_bruts(dossier: Path) -> list[dict]:
    out = []
    for p in sorted(dossier.rglob("*")):
        if p.suffix.lower() == ".json":
            blobs = [p.read_bytes()]
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                blobs = [z.read(n) for n in z.namelist() if n.lower().endswith(".json")]
        else:
            continue
        for b in blobs:
            try:
                d = json.loads(b.decode("utf-8-sig"))
            except ValueError:
                continue
            if isinstance(d, dict) and isinstance(d.get("entries"), list):
                out.append(d)
    return out


def retenus(digests: list[dict]) -> list[dict]:
    """Doublons : genereLe le plus récent ; corbeille exclue (comme l'outil, recalculé à part)."""
    par_uid: dict = {}
    sans_uid = []
    for d in digests:
        if d.get("uid"):
            if d["uid"] not in par_uid or (d.get("genereLe") or "") > (par_uid[d["uid"]].get("genereLe") or ""):
                par_uid[d["uid"]] = d
        else:
            sans_uid.append(d)
    return [d for d in list(par_uid.values()) + sans_uid if not d.get("corbeille")]


@pytest.fixture(scope="module")
def import_reel(tmp_path_factory):
    empreinte = lambda: {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in SAMPLES.rglob("*") if p.is_file()}
    avant = empreinte()
    sortie = tmp_path_factory.mktemp("reel") / "sortie"
    res, rapport = importer(SAMPLES, sortie, Config())
    assert empreinte() == avant, "samples/ a été modifié"
    return res, rapport, sortie


def test_lecture_sans_erreur(import_reel):
    res, rapport, sortie = import_reel
    assert res.nb_digests_lus == len(digests_bruts(SAMPLES)) > 0
    for f in ("releves.csv", "releves.xlsx", "releves.geojson", "rapport_import.txt"):
        assert (sortie / f).is_file()


def test_schemas(import_reel):
    res, _, _ = import_reel
    for v in res.visites:
        attendu = v.d.get("schemaVersion")
        if attendu in (1, 2):
            assert v.schema == attendu
        if attendu == 1:
            assert any(a.code == "SCHEMA_1" for a in v.anomalies)


def test_comptes_par_type(import_reel):
    res, _, _ = import_reel
    attendu = Counter(e.get("type") or "" for d in retenus(digests_bruts(SAMPLES)) for e in d["entries"]
                      if isinstance(e, dict))
    assert Counter(l["type"] for l in res.lignes) == attendu


def test_doublons(import_reel):
    res, _, _ = import_reel
    uids = Counter(d["uid"] for d in digests_bruts(SAMPLES) if d.get("uid"))
    for uid, n in uids.items():
        groupe = [v for v in res.visites if v.uid == uid]
        assert len(groupe) == n
        assert sum(v.statut != "doublon écarté" for v in groupe) == 1


def test_fichiers_extraits_identiques_et_relisibles(import_reel):
    res, _, sortie = import_reel
    for v in res.retenues:
        for l, e in zip(v.lignes, [e for e in v.d["entries"] if isinstance(e, dict)]):
            for col, cle in (("fichier_photo", "image"), ("fichier_audio", "audio"), ("fichier_joint", "fichier")):
                if l[col]:
                    octets = (sortie / l[col]).read_bytes()
                    assert octets == base64.b64decode(e[cle]["base64"]), l[col]   # sans recompression
            if l["fichier_photo"] and "PIECE_ILLISIBLE" not in l["anomalie"]:
                with Image.open(sortie / l["fichier_photo"]) as img:
                    img.load()
            if e.get("erreur"):
                assert "PIECE_ILLISIBLE" in l["anomalie"]


def test_positions_nulles_et_geojson(import_reel):
    res, _, sortie = import_reel
    fc = json.loads((sortie / "releves.geojson").read_text("utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == sum(1 for l in res.lignes if l["lat"] is not None)
    for f in fc["features"]:
        lng, lat = f["geometry"]["coordinates"]
        assert (lng, lat) == (f["properties"]["lng"], f["properties"]["lat"])
    for v in res.retenues:
        for l, e in zip(v.lignes, [e for e in v.d["entries"] if isinstance(e, dict)]):
            if e.get("position") is None:
                assert l["lat"] is None and "POSITION_ABSENTE" in l["anomalie"]
            elif isinstance(e["position"], dict) and l["lat"] is not None:
                assert (l["lng"], l["lat"]) == (e["position"]["lng"], e["position"]["lat"])


def test_themes(import_reel):
    res, _, _ = import_reel
    codes = set(Config().themes) | {"AUTRE"}
    assert {l["theme"] for l in res.lignes} <= codes
    for l in res.lignes:
        if not l["repere"]:
            assert "SANS_REPERE" in l["anomalie"]
