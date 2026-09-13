"""Penjaga paket — dipakai uji di tiap repo aplikasi.

Dua hal yang dijaga, dan keduanya pernah terjadi (QA X-22):
  1. `salinan_terlarang(repo)` — repo menyimpan berkas paket di luar folder
     vendored (mis. `app/web/static/app.css`). Itu penyalinan lagi.
  2. `vendor_selaras(repo)` — folder vendored `hmu_tampilan/` disunting tangan
     atau basi terhadap repo `tampilan/` bila repo itu ada di sebelahnya.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import BERKAS_PAKET

MANIFEST = "MANIFEST.sha256"
_ABAIKAN = {".venv", "node_modules", "__pycache__", ".git", "graphify-out", "hmu_tampilan"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def isi_manifest(akar_paket: Path) -> dict[str, str]:
    """Hash setiap berkas paket (relatif ke folder paket), terurut."""
    keluar = {}
    for p in sorted(akar_paket.rglob("*")):
        if p.is_file() and p.name != MANIFEST and "__pycache__" not in p.parts:
            keluar[str(p.relative_to(akar_paket))] = _sha(p)
    return keluar


def tulis_manifest(akar_paket: Path) -> Path:
    m = akar_paket / MANIFEST
    m.write_text("".join(f"{h}  {n}\n" for n, h in isi_manifest(akar_paket).items()))
    return m


def baca_manifest(akar_paket: Path) -> dict[str, str]:
    m = akar_paket / MANIFEST
    if not m.exists():
        return {}
    keluar = {}
    for baris in m.read_text().splitlines():
        h, _, n = baris.partition("  ")
        keluar[n] = h
    return keluar


def salinan_terlarang(akar_repo: Path) -> list[Path]:
    """Berkas bernama sama dengan berkas paket, di luar folder vendored."""
    temuan = []
    for p in akar_repo.rglob("*"):
        if any(bag in _ABAIKAN for bag in p.relative_to(akar_repo).parts[:-1]):
            continue
        if p.is_file() and p.name in BERKAS_PAKET:
            temuan.append(p.relative_to(akar_repo))
    return temuan


def vendor_selaras(akar_repo: Path) -> list[str]:
    """Selisih antara isi `hmu_tampilan/` vendored dan manifest-nya, ditambah
    selisih terhadap repo `tampilan/` di sebelah bila ada. Kosong = selaras."""
    vend = akar_repo / "hmu_tampilan"
    if not vend.exists():
        return ["folder hmu_tampilan/ tidak ada — jalankan scripts/sinkron.py di repo tampilan"]
    dicatat, nyata = baca_manifest(vend), isi_manifest(vend)
    selisih = [f"{n}: {'hilang' if n not in nyata else 'berubah'}" for n in dicatat if nyata.get(n) != dicatat[n]]
    selisih += [f"{n}: tak ada di manifest" for n in nyata if n not in dicatat]
    sumber = akar_repo.parent / "tampilan" / "hmu_tampilan"
    if sumber.exists():
        asli = isi_manifest(sumber)
        if asli != nyata:
            selisih.append("basi terhadap repo tampilan/ — jalankan scripts/sinkron.py")
    return selisih
