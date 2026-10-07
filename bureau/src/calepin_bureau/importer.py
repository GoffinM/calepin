"""Commande « importer » : lecture, consolidation et écriture de toutes les sorties."""
from __future__ import annotations

import shutil
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import Config
from .consolidation import Extracteur, Resultat, ligne_visite, selectionner, traiter_visite
from .lecture import lire_source
from .sorties import ecrire_csv, ecrire_geojson, ecrire_rapport, ecrire_xlsx

MARQUEUR = ".calepin-bureau"
SORTIES_FICHIERS = ("releves.csv", "releves.xlsx", "releves.geojson", "rapport_import.txt")
SORTIES_DOSSIERS = ("photos", "audio", "fichiers")


class ErreurImport(Exception):
    pass


def _dans(enfant: Path, parent: Path) -> bool:
    try:
        enfant.relative_to(parent)
        return True
    except ValueError:
        return False


def preparer_sortie(source: Path, sortie: Path) -> None:
    """Vérifie que la sortie ne touche pas aux données d'entrée, puis vide l'ancienne sortie."""
    src, out = source.resolve(), sortie.resolve()
    dossier_src = src if src.is_dir() else src.parent
    if any(p.name.lower() == "samples" for p in [out, *out.parents]):
        raise ErreurImport(f"refus d'écrire dans un dossier « samples » : {sortie}")
    if _dans(out, dossier_src) and src.is_dir():
        raise ErreurImport("le dossier de sortie ne doit pas être dans le dossier source")
    if _dans(dossier_src, out) or out == src:
        raise ErreurImport("le dossier de sortie ne doit pas contenir les données source")
    if out.exists() and not out.is_dir():
        raise ErreurImport(f"la sortie existe et n'est pas un dossier : {sortie}")
    if out.is_dir() and any(out.iterdir()):
        if not (out / MARQUEUR).is_file():
            raise ErreurImport(f"le dossier de sortie n'est pas vide et n'a pas été créé par calepin-bureau : "
                               f"{sortie} (choisir un dossier vide ou inexistant)")
        # Sortie d'un import précédent : on ne retire que ce que l'outil produit.
        for nom in SORTIES_DOSSIERS:
            if (out / nom).is_dir():
                shutil.rmtree(out / nom)
        for nom in SORTIES_FICHIERS:
            if (out / nom).is_file():
                (out / nom).unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARQUEUR).write_text("Dossier produit par calepin-bureau : il est réécrit à chaque import.\n",
                                encoding="utf-8")


def importer(source: str | Path, sortie: str | Path, config: Config, fuseau: str | None = None,
             inclure_corbeille: bool = False) -> tuple[Resultat, str]:
    source, sortie = Path(source), Path(sortie)
    nom_fuseau = fuseau or config.fuseau
    try:
        tz = ZoneInfo(nom_fuseau)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ErreurImport(f"fuseau horaire inconnu : {nom_fuseau!r} (sous Windows : pip install tzdata)") from e
    if not source.exists():
        raise ErreurImport(f"source introuvable : {source}")

    lecture = lire_source(source)          # lecture complète avant toute écriture
    preparer_sortie(source, sortie)

    res = Resultat(nb_digests_lus=len(lecture.digests))
    if not lecture.digests:
        res.avertissements.append("aucun digest trouvé dans la source")
    selectionner(lecture, inclure_corbeille, res)
    extracteur = Extracteur(sortie, config, res)
    for v in res.retenues:
        traiter_visite(v, config, tz, extracteur)

    lignes_visites = [ligne_visite(v, tz) for v in res.visites]
    ecrire_csv(sortie / "releves.csv", res.lignes, config.csv_separateur)
    ecrire_xlsx(sortie / "releves.xlsx", res, lignes_visites)
    nb_points = ecrire_geojson(sortie / "releves.geojson", res.lignes)
    rapport = ecrire_rapport(sortie / "rapport_import.txt", res, str(source), sortie, nom_fuseau, config.source,
                             inclure_corbeille, nb_points)
    return res, rapport
