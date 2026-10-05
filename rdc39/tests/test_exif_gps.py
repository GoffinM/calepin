#!/usr/bin/env python3
"""
Test de l'écriture EXIF GPS des JPEG exportés (fonction jpegWithGpsExif de ../index.html).

La fonction est extraite telle quelle de index.html (entre les marqueurs EXIF-WRITER-BEGIN/END),
exécutée sous Node, puis les fichiers produits sont relus avec Pillow.

Cas couverts :
  JPEG d'entrée : sans EXIF (JFIF), EXIF big-endian (Pillow, piexif), segment Exif VIDE façon
                  Safari, EXIF little-endian (construit à la main) ;
  JPEG de sortie : TIFF big-endian ("MM", défaut de l'app) et little-endian ("II") ;
  hémisphères N/E et S/W, fuseau horaire positif et négatif ;
  sans position -> fichier strictement inchangé ; fichier non JPEG -> inchangé.
Vérifie : latitude/longitude (±1e-6°), références N/S E/W, DateTimeOriginal (heure locale),
OffsetTimeOriginal, altitude, précision, UN SEUL segment APP1/Exif, ancien EXIF (Make) retiré,
pixels identiques à l'original.

Prérequis : python3 + Pillow + piexif, node.   Lancer : python3 rdc39/tests/test_exif_gps.py
"""
import io, json, os, re, struct, subprocess, sys, tempfile

from PIL import Image
import piexif

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "index.html")


def extract_writer():
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"/\* EXIF-WRITER-BEGIN \*/(.*?)/\* EXIF-WRITER-END \*/", src, re.S)
    if not m:
        sys.exit("marqueurs EXIF-WRITER introuvables dans index.html")
    return m.group(1)


def make_inputs(d):
    img = Image.new("RGB", (64, 48))
    for x in range(64):
        for y in range(48):
            img.putpixel((x, y), (x * 4, y * 5, 128))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90); plain = buf.getvalue()
    files = {"plain": plain}
    # EXIF big-endian écrit par Pillow (Make + ancien GPS, qui doivent disparaître)
    ex = Image.Exif(); ex[0x010F] = "OldCam"
    g = ex.get_ifd(0x8825); g[1] = "S"; g[2] = (10.0, 0.0, 0.0)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90, exif=ex.tobytes()); files["pillow_be"] = buf.getvalue()
    # EXIF big-endian écrit par piexif
    out = io.BytesIO()
    piexif.insert(piexif.dump({"0th": {piexif.ImageIFD.Make: b"OldCam"}, "Exif": {}, "GPS": {}, "1st": {}}), plain, out)
    files["piexif_be"] = out.getvalue()
    # Segment Exif vide (ce que produit le canvas de Safari)
    tiff = b"MM\x00\x2a\x00\x00\x00\x08" + b"\x00\x00" + b"\x00\x00\x00\x00"
    files["safari_empty"] = plain[:2] + b"\xff\xe1" + struct.pack(">H", 8 + len(tiff)) + b"Exif\x00\x00" + tiff + plain[2:]
    # EXIF little-endian construit à la main (IFD0 : Make)
    make = b"OldCam\x00"
    ifd = struct.pack("<H", 1) + struct.pack("<HHII", 0x010F, 2, len(make), 8 + 2 + 12 + 4) + struct.pack("<I", 0)
    tiff = b"II\x2a\x00" + struct.pack("<I", 8) + ifd + make
    files["manual_le"] = plain[:2] + b"\xff\xe1" + struct.pack(">H", 8 + len(tiff)) + b"Exif\x00\x00" + tiff + plain[2:]
    # Structure produite par le canvas de Safari : SOI, APP0 JFIF, APP1 Exif VIDE de 76 octets
    # (IFD0 = seulement ExifOffset ; IFD Exif = ColorSpace, PixelXDimension, PixelYDimension),
    # puis bloc Photoshop (APP13), puis l'image.
    files["safari_canvas"] = safari_canvas_jpeg(plain)
    for k, v in files.items():
        open(os.path.join(d, k + ".jpg"), "wb").write(v)
    return list(files)


def safari_canvas_jpeg(plain):
    assert plain[2:4] == b"\xff\xe0"
    app0_len = struct.unpack(">H", plain[4:6])[0]
    app0 = plain[2:4 + app0_len]
    rest = plain[4 + app0_len:]
    ifd0 = struct.pack(">H", 1) + struct.pack(">HHII", 0x8769, 4, 1, 26) + struct.pack(">I", 0)
    exif_ifd = (struct.pack(">H", 3) + struct.pack(">HHIHH", 0xA001, 3, 1, 1, 0)
                + struct.pack(">HHII", 0xA002, 4, 1, 64) + struct.pack(">HHII", 0xA003, 4, 1, 48) + struct.pack(">I", 0))
    tiff = b"MM\x00\x2a\x00\x00\x00\x08" + ifd0 + exif_ifd
    app1 = b"\xff\xe1" + struct.pack(">H", 2 + 6 + len(tiff)) + b"Exif\x00\x00" + tiff
    assert struct.unpack(">H", app1[2:4])[0] == 76, "le segment Exif Safari doit faire 76 octets"
    ps = b"Photoshop 3.0\x00" + b"8BIM" + b"\x04\x04" + b"\x00\x00" + struct.pack(">I", 0)
    app13 = b"\xff\xed" + struct.pack(">H", 2 + len(ps)) + ps
    return b"\xff\xd8" + app0 + app1 + app13 + rest


def segment_markers(path):
    b = open(path, "rb").read(); out = []; i = 2
    while i + 4 <= len(b) and b[i] == 0xFF and b[i + 1] != 0xDA:
        L = (b[i + 2] << 8) | b[i + 3]
        tag = b[i + 4:i + 10]
        out.append("APP1/Exif(%d)" % L if b[i + 1] == 0xE1 and tag == b"Exif\x00\x00" else "%02X" % b[i + 1])
        i += 2 + L
    return out


CASES = [
    # suffixe, options JS, position, attendu (lat, lon, refLat, refLon, DTO, offset, ordre)
    ("MM", {"littleEndian": False, "tzOffsetMinutes": 120}, {"lat": 1.5351234, "lng": 30.2943321, "accuracy": 6, "altitude": 1187},
     (1.5351234, 30.2943321, "N", "E", "2026:10:05 15:04:05", "+02:00", b"MM")),
    ("II", {"littleEndian": True, "tzOffsetMinutes": 120}, {"lat": 1.5351234, "lng": 30.2943321, "accuracy": 6, "altitude": 1187},
     (1.5351234, 30.2943321, "N", "E", "2026:10:05 15:04:05", "+02:00", b"II")),
    ("SW", {"tzOffsetMinutes": -330}, {"lat": -1.9536, "lng": -30.0605},
     (-1.9536, -30.0605, "S", "W", "2026:10:05 07:34:05", "-05:30", b"MM")),
]
TS = 1791205445000  # 2026-10-05 13:04:05 UTC


def run_node(d, names, writer):
    js = writer + """
const fs = require('fs'); const d = process.argv[2]; const names = JSON.parse(process.argv[3]); const cases = JSON.parse(process.argv[4]);
for (const n of names) {
  const b = fs.readFileSync(d + '/' + n + '.jpg'); const ab = b.buffer.slice(b.byteOffset, b.byteOffset + b.length);
  for (const [suf, opts, loc] of cases) fs.writeFileSync(`${d}/out_${n}_${suf}.jpg`, Buffer.from(jpegWithGpsExif(ab, loc, %d, opts)));
  fs.writeFileSync(`${d}/out_${n}_nopos.jpg`, Buffer.from(jpegWithGpsExif(ab, null, %d)));
}
const png = new Uint8Array([0x89, 0x50, 0x4E, 0x47, 1, 2]).buffer;
if (jpegWithGpsExif(png, {lat: 1, lng: 2}, %d) !== png) { console.error('non-JPEG modifié'); process.exit(1); }
""" % (TS, TS, TS)
    path = os.path.join(d, "run.js"); open(path, "w").write(js)
    subprocess.run(["node", path, d, json.dumps(names), json.dumps([[c[0], c[1], c[2]] for c in CASES])], check=True)


def exif_segments(path):
    b = open(path, "rb").read(); n = 0; order = None; i = 2
    while i + 4 <= len(b) and b[i] == 0xFF and b[i + 1] != 0xDA:
        L = (b[i + 2] << 8) | b[i + 3]
        if b[i + 1] == 0xE1 and b[i + 4:i + 10] == b"Exif\x00\x00":
            n += 1; order = b[i + 10:i + 12]
        i += 2 + L
    return n, order


def dms(v):
    return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600


def main():
    d = tempfile.mkdtemp(prefix="exif_")
    names = make_inputs(d)
    run_node(d, names, extract_writer())
    fails = 0
    for n in names:
        ref = Image.open(os.path.join(d, n + ".jpg")); ref.load()
        in_order = exif_segments(os.path.join(d, n + ".jpg"))[1]
        for suf, _, loc, exp in CASES:
            p = os.path.join(d, f"out_{n}_{suf}.jpg")
            im = Image.open(p); im.load()
            ex = im.getexif(); g = ex.get_ifd(0x8825); e = ex.get_ifd(0x8769)
            lat = dms(g[2]) * (1 if g[1] == "N" else -1)
            lon = dms(g[4]) * (1 if g[3] == "E" else -1)
            nseg, order = exif_segments(p)
            ok = (abs(lat - exp[0]) < 1e-6 and abs(lon - exp[1]) < 1e-6 and g[1] == exp[2] and g[3] == exp[3]
                  and e.get(0x9003) == exp[4] and e.get(0x9011) == exp[5] and order == exp[6] and nseg == 1
                  and 0x010F not in ex and im.size == ref.size
                  and list(im.get_flattened_data()) == list(ref.get_flattened_data()))
            if "altitude" in loc:
                ok = ok and float(g[6]) == loc["altitude"] and g[5] in (0, b"\x00") and float(g[0x1F]) == loc["accuracy"]
            print(f"{'OK  ' if ok else 'FAIL'} entrée {n:13s} ({(in_order or b'--').decode()}) -> sortie {order.decode()}  "
                  f"{lat:.7f} {g[1]} / {lon:.7f} {g[3]}  {e.get(0x9003)} {e.get(0x9011)}")
            fails += not ok
        if n == "safari_canvas":
            before = segment_markers(os.path.join(d, n + ".jpg"))
            for suf in ("MM", "II"):
                after = segment_markers(os.path.join(d, f"out_{n}_{suf}.jpg"))
                im = Image.open(os.path.join(d, f"out_{n}_{suf}.jpg"))
                ex = im.getexif()
                ok = (before[:3] == ["E0", "APP1/Exif(76)", "ED"] and after[0] == "E0" and after[1].startswith("APP1/Exif(")
                      and after[1] != "APP1/Exif(76)" and after.count("ED") == 1 and sum(a.startswith("APP1/Exif") for a in after) == 1
                      and 0xA002 not in ex.get_ifd(0x8769))  # ancien IFD Exif (dimensions) bien retiré
                print(f"{'OK  ' if ok else 'FAIL'} Safari {suf} : segments avant {before[:3]} -> après {after[:3]} (Exif vide remplacé, JFIF en tête, Photoshop conservé)")
                fails += not ok
        same = open(os.path.join(d, n + ".jpg"), "rb").read() == open(os.path.join(d, f"out_{n}_nopos.jpg"), "rb").read()
        print(f"{'OK  ' if same else 'FAIL'} entrée {n:13s} sans position -> fichier inchangé")
        fails += not same
    print("ÉCHECS :", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
