"""Lecture des digests : dossier de *.json (et de *.zip), ou ZIP d'export groupé avec index.json.

Les données d'entrée ne sont jamais modifiées : fichiers et ZIP sont ouverts en lecture seule.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_INDEX = "rdc39-export-index"


@dataclass
class DigestLu:
    source: str                 # « fichier.json » ou « export.zip!fichier.json »
    donnees: dict


@dataclass
class Lecture:
    digests: list[DigestLu] = field(default_factory=list)
    index: list[tuple[str, dict]] = field(default_factory=list)       # (source, index.json)
    illisibles: list[tuple[str, str]] = field(default_factory=list)   # (source, raison)
    ignores: list[tuple[str, str]] = field(default_factory=list)      # JSON qui ne sont pas des digests


def _decoder(octets: bytes, source: str, lecture: Lecture) -> None:
    try:
        donnees = json.loads(octets.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        lecture.illisibles.append((source, f"JSON illisible : {e}"))
        return
    if isinstance(donnees, dict) and donnees.get("schema") == SCHEMA_INDEX:
        lecture.index.append((source, donnees))
    elif isinstance(donnees, dict) and isinstance(donnees.get("entries"), list):
        lecture.digests.append(DigestLu(source, donnees))
    elif isinstance(donnees, dict) and "entries" in donnees:
        lecture.illisibles.append((source, "« entries » n'est pas une liste"))
    else:
        lecture.ignores.append((source, "pas un digest (aucun champ « entries »)"))


def _lire_zip(chemin: Path, nom_affiche: str, lecture: Lecture) -> None:
    try:
        with zipfile.ZipFile(chemin) as z:
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                if info.is_dir() or not info.filename.lower().endswith(".json"):
                    continue
                source = f"{nom_affiche}!{info.filename}"
                try:
                    octets = z.read(info)
                except (zipfile.BadZipFile, OSError, RuntimeError) as e:
                    lecture.illisibles.append((source, f"lecture impossible dans le ZIP : {e}"))
                    continue
                _decoder(octets, source, lecture)
    except (zipfile.BadZipFile, OSError) as e:
        lecture.illisibles.append((nom_affiche, f"ZIP illisible : {e}"))


def lire_source(source: str | Path) -> Lecture:
    """Lit un dossier (récursivement : *.json et *.zip) ou un fichier .zip / .json."""
    source = Path(source)
    lecture = Lecture()
    if source.is_dir():
        fichiers = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in (".json", ".zip"))
        for p in fichiers:
            nom = p.relative_to(source).as_posix()
            if p.suffix.lower() == ".zip":
                _lire_zip(p, nom, lecture)
            else:
                try:
                    _decoder(p.read_bytes(), nom, lecture)
                except OSError as e:
                    lecture.illisibles.append((nom, f"lecture impossible : {e}"))
    elif source.is_file() and source.suffix.lower() == ".zip":
        _lire_zip(source, source.name, lecture)
    elif source.is_file() and source.suffix.lower() == ".json":
        _decoder(source.read_bytes(), source.name, lecture)
    else:
        raise FileNotFoundError(f"source introuvable ou non prise en charge (dossier, .zip ou .json) : {source}")
    return lecture
