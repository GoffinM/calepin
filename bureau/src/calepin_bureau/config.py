"""Lecture de config.yaml (valeurs par défaut si absent)."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAUTS = {
    "fuseau": "Africa/Kigali",
    "themes": ["FONC", "OCC", "SOC", "ACC", "HYD", "RIV", "TRAV", "ERO", "EMP", "ACT"],
    "theme_defaut": "AUTRE",
    "precision_max_m": 50,
    "audio_silence_db": -60,
    "ffmpeg": "",
    "longueur_nom_max": 120,
    "csv_separateur": ";",
}


class ErreurConfig(Exception):
    pass


@dataclass
class Config:
    fuseau: str = DEFAUTS["fuseau"]
    themes: list[str] = field(default_factory=lambda: list(DEFAUTS["themes"]))
    theme_defaut: str = DEFAUTS["theme_defaut"]
    precision_max_m: float = DEFAUTS["precision_max_m"]
    audio_silence_db: float = DEFAUTS["audio_silence_db"]
    ffmpeg: str = DEFAUTS["ffmpeg"]
    longueur_nom_max: int = DEFAUTS["longueur_nom_max"]
    csv_separateur: str = DEFAUTS["csv_separateur"]
    source: str = "valeurs par défaut"


def charger_config(chemin: str | Path | None = None) -> Config:
    """Charge `chemin`, sinon ./config.yaml s'il existe, sinon les valeurs par défaut."""
    valeurs = copy.deepcopy(DEFAUTS)
    source = "valeurs par défaut"
    if chemin is None and Path("config.yaml").is_file():
        chemin = Path("config.yaml")
    if chemin is not None:
        chemin = Path(chemin)
        if not chemin.is_file():
            raise ErreurConfig(f"fichier de configuration introuvable : {chemin}")
        try:
            lu = yaml.safe_load(chemin.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError as e:
            raise ErreurConfig(f"{chemin} : YAML invalide ({e})") from e
        if not isinstance(lu, dict):
            raise ErreurConfig(f"{chemin} : le contenu doit être une liste de clés « nom: valeur »")
        inconnues = sorted(set(lu) - set(DEFAUTS))
        if inconnues:
            raise ErreurConfig(f"{chemin} : clé(s) inconnue(s) : {', '.join(inconnues)}")
        valeurs.update({k: v for k, v in lu.items() if v is not None})
        source = str(chemin)

    themes = valeurs["themes"]
    if not isinstance(themes, list) or not all(isinstance(t, str) and t.strip() for t in themes):
        raise ErreurConfig("« themes » doit être une liste de codes (texte)")
    try:
        return Config(
            fuseau=str(valeurs["fuseau"]),
            themes=[t.strip().upper() for t in themes],
            theme_defaut=str(valeurs["theme_defaut"]).strip() or "AUTRE",
            precision_max_m=float(valeurs["precision_max_m"]),
            audio_silence_db=float(valeurs["audio_silence_db"]),
            ffmpeg=str(valeurs["ffmpeg"] or ""),
            longueur_nom_max=int(valeurs["longueur_nom_max"]),
            csv_separateur=str(valeurs["csv_separateur"]) or ";",
            source=source,
        )
    except (TypeError, ValueError) as e:
        raise ErreurConfig(f"valeur de configuration invalide : {e}") from e
