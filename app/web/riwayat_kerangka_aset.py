"""Aset build native untuk kerangka Riwayat, bukan cache data pengguna."""
from functools import lru_cache
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ASET = (
    ("laporan-riwayat.css", "hmu_tampilan/static/laporan-riwayat.css", "style"),
    ("laporan-kontrol.css", "hmu_tampilan/static/laporan-kontrol.css", "style"),
    ("laporan-kontrol.js", "hmu_tampilan/static/laporan-kontrol.js", "script"),
    ("riwayat.css", "app/web/static/riwayat.css", "style"),
    ("riwayat-sosoh-desain.css", "app/web/static/riwayat-sosoh-desain.css", "style"),
    ("riwayat-daftar-proses.css", "app/web/static/riwayat-daftar-proses.css", "style"),
    ("halaman-bertahap.js", "app/web/static/halaman-bertahap.js", "script"),
)
GILING = ("riwayat-giling-daftar.css", "app/web/static/riwayat-giling-daftar.css", "style")

@lru_cache(maxsize=3)
def kode(kind):
    result = []
    total = 0
    for name, relative, tag in (*ASET, *((GILING,) if kind == "riwayat-giling" else ())):
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Aset Riwayat tidak tersedia")
        code = path.read_text()
        total += len(code.encode())
        if not code or total > 196608 or "</"+tag in code.lower():
            raise ValueError("Batas aset Riwayat tidak sesuai")
        if tag == "style" and re.search(r"@import|url\s*\(", code, re.I):
            raise ValueError("Aset Riwayat membutuhkan URL tambahan")
        result.append((name, code, tag))
    return tuple(result)

def paket_lokal(body, kind):
    html = body.decode()
    for name, code, tag in kode(kind):
        if tag == "style":
            pattern = r'<link rel="stylesheet" href="/static/' + re.escape(name) + r'\?[^"<>]+">'
        else:
            pattern = r'<script src="/static/' + re.escape(name) + r'\?[^"<>]+" defer></script>'
        html, count = re.subn(pattern, lambda _: "<"+tag+' data-riwayat-aset-native="'+name+'">'+code+"</"+tag+">", html)
        if count != 1:
            raise ValueError("Referensi aset Riwayat tidak tunggal")
    return html.encode()
