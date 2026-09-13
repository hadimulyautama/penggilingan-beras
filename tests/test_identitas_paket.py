"""Identitas adalah paket bersama `hmu_identitas` (Tahap 2 rancang ulang).

Tiga hal dijaga: folder vendored selaras dengan manifest & repo core/;
repo ini tak mendefinisikan ulang fungsi sandi milik paket; dan peran tak
pernah disebut harfiah di `app/` (pemeriksa AST, dulu hanya ada di kantor).
"""
from __future__ import annotations

import pathlib

from hmu_identitas import penjaga

AKAR = pathlib.Path(__file__).resolve().parents[1]


def test_vendored_selaras():
    assert penjaga.vendor_selaras(AKAR) == []
    assert penjaga.vendor_selaras(AKAR, "hmu_core") == []


def test_tak_ada_definisi_ganda_fungsi_sandi():
    assert penjaga.definisi_ganda(AKAR / "app") == []


def test_peran_tak_disebut_harfiah():
    temuan = penjaga.peran_harfiah(AKAR / "app")
    assert not temuan, "pakai hmu_identitas.peran: " + "; ".join(temuan)
