"""Noms de fichiers sûrs sous Windows : sans accents, sans caractères interdits, longueur bornée."""
from __future__ import annotations

import os
import re
import unicodedata

# Ligatures et lettres que la décomposition Unicode ne ramène pas à l'ASCII.
_REMPLACEMENTS = {"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss", "ø": "o", "Ø": "O",
                  "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "’": "-", "'": "-"}
_RESERVES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def assainir(texte: str | None, defaut: str = "sans-nom", longueur_max: int = 60) -> str:
    """Ramène `texte` à [A-Za-z0-9._-], tirets simples, sans nom réservé Windows."""
    s = "".join(_REMPLACEMENTS.get(c, c) for c in (texte or ""))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)          # espaces, <>:"/\|?*, contrôles, non-ASCII
    s = re.sub(r"-{2,}", "-", s)
    s = s[:longueur_max].strip("-._ ")
    if not s:
        s = defaut
    if s.split(".")[0].upper() in _RESERVES:
        s = "_" + s
    return s


def nom_media(visite: str, numero: str, libelle: str, extension: str, longueur_max: int = 120) -> str:
    """{visite}_{NN}_{libelle}{extension}, tronqué (libellé d'abord) à `longueur_max` caractères."""
    fixe = len(numero) + 2 + len(extension)
    reste = max(longueur_max - fixe, 2)
    visite = visite[: max(reste // 2, 1)].strip("-._") or "v"
    libelle = libelle[: max(reste - len(visite), 1)].strip("-._") or "x"
    return f"{visite}_{numero}_{libelle}{extension}"


def chemin_os(chemin) -> str:
    """Chemin utilisable sous Windows au-delà de 260 caractères (préfixe \\\\?\\)."""
    p = os.path.abspath(str(chemin))
    if os.name == "nt" and len(p) >= 240 and not p.startswith("\\\\?\\"):
        p = "\\\\?\\" + p
    return p
