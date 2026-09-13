"""Penjaga paket tampilan (temuan QA X-22, Tahap 1 rancang ulang).

Sumber tunggal CSS/JS/templat dasar adalah repo `tampilan/` (paket
`hmu_tampilan`), di-vendor ke `hmu_tampilan/` di sini. Dua hal yang dijaga:
tak ada berkas paket yang disalin lagi ke tempat lain di repo ini, dan
salinan vendored tidak disunting tangan atau basi.
"""
from __future__ import annotations

import pathlib

from hmu_tampilan import penjaga

AKAR = pathlib.Path(__file__).resolve().parents[1]


def test_tak_ada_salinan_berkas_paket_di_repo_ini():
    assert penjaga.salinan_terlarang(AKAR) == []


def test_vendored_selaras_dengan_manifest_dan_sumbernya():
    assert penjaga.vendor_selaras(AKAR) == []


def test_versi_aset_satu_nomor_dari_paket():
    import hmu_tampilan
    from app.web import tampilan
    assert tampilan.VERSI == hmu_tampilan.VERSI
