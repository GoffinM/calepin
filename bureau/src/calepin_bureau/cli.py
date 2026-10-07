"""Point d'entrée : calepin-bureau importer <dossier_ou_zip> --sortie <dossier> [--fuseau …]."""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from . import __version__
from .config import ErreurConfig, charger_config
from .importer import ErreurImport, importer


def _parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="calepin-bureau",
                                description="Consolidation locale des relevés RDC39-Calepin (digests JSON).")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sous = p.add_subparsers(dest="commande", required=True)
    imp = sous.add_parser("importer", help="lire des digests et produire tableaux, GeoJSON et fichiers")
    imp.add_argument("source", help="dossier de digests *.json (et/ou *.zip), ou ZIP d'export groupé")
    imp.add_argument("--sortie", required=True, help="dossier de sortie (créé ; réécrit à chaque import)")
    imp.add_argument("--fuseau", help="fuseau horaire des heures locales (défaut : config.yaml, Africa/Kigali)")
    imp.add_argument("--inclure-corbeille", action="store_true", help="inclure les visites en corbeille")
    imp.add_argument("--config", help="fichier de configuration (défaut : ./config.yaml s'il existe)")
    return p


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):      # console Windows : accents sans erreur d'encodage
        try:
            flux.reconfigure(errors="replace")
        except AttributeError:
            pass
    args = _parseur().parse_args(argv)
    try:
        config = charger_config(args.config)
        res, _ = importer(args.source, args.sortie, config, fuseau=args.fuseau,
                          inclure_corbeille=args.inclure_corbeille)
    except (ErreurConfig, ErreurImport, FileNotFoundError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 2
    types = Counter(l["type"] for l in res.lignes)
    graves = Counter(a.gravite for a in res.anomalies)
    print(f"{len(res.retenues)} visite(s) importée(s) sur {res.nb_digests_lus} digest(s) lu(s) ; "
          f"{len(res.lignes)} entrée(s) : " + ", ".join(f"{t} {n}" for t, n in sorted(types.items())))
    print(f"Anomalies : {graves.get('erreur', 0)} erreur(s), {graves.get('attention', 0)} attention, "
          f"{graves.get('info', 0)} info — détail dans rapport_import.txt")
    for a in res.avertissements:
        print(f"Avertissement : {a}")
    print(f"Sortie : {args.sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
