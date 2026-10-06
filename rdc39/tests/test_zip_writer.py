#!/usr/bin/env python3
"""
Test du générateur ZIP de l'export groupé (createZipBuilder / crc32 de ../index.html).

Le code est extrait tel quel de index.html (marqueurs ZIP-WRITER-BEGIN/END), exécuté sous Node,
puis l'archive produite est relue avec des outils EXTERNES : `unzip -t` (CRC vérifiés) et
le module zipfile de Python (testzip = CRC, contenu comparé octet par octet).

Cas : JSON, nom accentué (UTF-8), binaire aléatoire de 3 Mo, fichier vide, nom en double
(renommé), CRC de référence ("123456789" -> cbf43926).

Prérequis : python3, node, unzip.   Lancer : python3 rdc39/tests/test_zip_writer.py
"""
import json, os, re, shutil, subprocess, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "index.html")


def main():
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"/\* ZIP-WRITER-BEGIN \*/(.*?)/\* ZIP-WRITER-END \*/", src, re.S)
    if not m:
        sys.exit("marqueurs ZIP-WRITER introuvables dans index.html")
    d = tempfile.mkdtemp(prefix="zip_")
    binref = os.urandom(3 * 1024 * 1024)
    open(os.path.join(d, "bin.ref"), "wb").write(binref)
    js = m.group(1) + r"""
const fs = require('fs'); const d = process.argv[2];
const ref = crc32(new TextEncoder().encode('123456789')).toString(16);
if (ref !== 'cbf43926') { console.error('CRC de référence faux : ' + ref); process.exit(1); }
const z = createZipBuilder({ date: new Date(2026, 9, 6, 14, 37, 22), toBlobPart: (u8) => u8 });
z.add('index.json', JSON.stringify({ ok: true, texte: 'Pont – niveau PHE 1,80 m' }));
z.add('2026-10-06_Pont é ñ_ab12.json', '{"repere":"Pont é ñ"}');
z.add('binaire.bin', new Uint8Array(fs.readFileSync(d + '/bin.ref')));
z.add('vide.json', '');
const dup = z.add('index.json', 'doublon');
const parts = z.finishParts();
fs.writeFileSync(d + '/test.zip', Buffer.concat(parts.map(p => Buffer.from(p))));
console.log(JSON.stringify({ dup }));
"""
    path = os.path.join(d, "run.js"); open(path, "w").write(js)
    out = json.loads(subprocess.run(["node", path, d], check=True, capture_output=True, text=True).stdout)
    fails = 0

    def check(name, ok, extra=""):
        nonlocal fails
        print(("OK   " if ok else "FAIL ") + name + (("  " + extra) if extra else ""))
        fails += not ok

    zp = os.path.join(d, "test.zip")
    r = subprocess.run(["unzip", "-t", zp], capture_output=True, text=True)
    check("unzip -t : aucune erreur (CRC vérifiés)", r.returncode == 0 and "No errors detected" in r.stdout, r.stdout.strip().splitlines()[-1])
    z = zipfile.ZipFile(zp)
    check("zipfile.testzip : tous les CRC corrects", z.testzip() is None)
    names = [i.filename for i in z.infolist()]
    check("5 fichiers, noms attendus (doublon renommé)", names == ["index.json", "2026-10-06_Pont é ñ_ab12.json", "binaire.bin", "vide.json", "index_2.json"] and out["dup"] == "index_2.json", str(names))
    check("méthode stored (0) et noms UTF-8 (bit 11)", all(i.compress_type == 0 and i.flag_bits & 0x800 for i in z.infolist()))
    check("binaire de 3 Mo identique à l'original", z.read("binaire.bin") == binref)
    check("JSON relisible", json.loads(z.read("index.json"))["texte"] == "Pont – niveau PHE 1,80 m" and json.loads(z.read("2026-10-06_Pont é ñ_ab12.json"))["repere"] == "Pont é ñ")
    check("fichier vide", z.read("vide.json") == b"")
    check("date DOS", z.infolist()[0].date_time == (2026, 10, 6, 14, 37, 22))
    shutil.rmtree(d, ignore_errors=True)
    print("ÉCHECS :", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
