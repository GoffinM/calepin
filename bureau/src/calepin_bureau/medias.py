"""Médias : extensions, contrôle des photos (EXIF GPS) et des audios (volume via ffmpeg)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .noms import chemin_os

_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/heic": ".heic", "image/heif": ".heif", "image/gif": ".gif",
    "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
    "audio/aac": ".aac", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "video/webm": ".webm", "video/mp4": ".mp4",
    "application/pdf": ".pdf", "text/plain": ".txt", "text/csv": ".csv",
    "application/json": ".json", "application/zip": ".zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc", "application/vnd.ms-excel": ".xls",
}

GPS_IFD = 0x8825


def extension_pour(mime: str | None, defaut: str = ".bin") -> str:
    """« audio/webm;codecs=opus » -> « .webm »."""
    base = (mime or "").split(";")[0].strip().lower()
    return _EXTENSIONS.get(base, defaut)


def est_jpeg(octets: bytes) -> bool:
    return octets[:3] == b"\xff\xd8\xff"


def controler_photo(chemin: Path) -> tuple[bool, bool | None, str | None]:
    """Relit le fichier extrait. Renvoie (lisible, a_gps_exif, erreur)."""
    try:
        with Image.open(chemin_os(chemin)) as img:
            exif = img.getexif()
            gps = exif.get_ifd(GPS_IFD) if exif else {}
            a_gps = bool(gps) and 2 in gps and 4 in gps     # GPSLatitude et GPSLongitude
        with Image.open(chemin_os(chemin)) as img:
            img.load()                                       # décode réellement les pixels
        return True, a_gps, None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        return False, None, str(e) or e.__class__.__name__


def trouver_ffmpeg(chemin_config: str) -> str | None:
    if chemin_config:
        return chemin_config if Path(chemin_config).is_file() else shutil.which(chemin_config)
    return shutil.which("ffmpeg")


_RE_MOYEN = re.compile(r"mean_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB")


def volume_moyen_db(ffmpeg: str, chemin: Path, delai_s: int = 300) -> tuple[float | None, str | None]:
    """Volume moyen mesuré par le filtre volumedetect. Renvoie (dB, erreur)."""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-i", chemin_os(chemin), "-vn", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, timeout=delai_s,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"ffmpeg n'a pas pu s'exécuter : {e}"
    sortie = r.stderr.decode("utf-8", "replace")
    m = _RE_MOYEN.search(sortie)
    if not m:
        derniere = sortie.strip().splitlines()[-1] if sortie.strip() else f"code {r.returncode}"
        return None, f"volume non mesuré par ffmpeg ({derniere})"
    return (float("-inf") if m.group(1) == "-inf" else float(m.group(1))), None
