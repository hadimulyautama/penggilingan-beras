"""Melihat sebagai peran lain — hanya boleh MENURUN.

Kukinya sengaja tidak ditandatangani. Itu aman justru karena penjepitannya:
peran yang diminta tak pernah boleh lebih tinggi dari peran asli, jadi
mengutak-atik kuki paling jauh hanya membuat diri sendiri lebih tak berdaya.
Kalau penjepitan ini bocor, kuki polos berubah menjadi kenaikan pangkat.
"""
from __future__ import annotations

import inspect

from app.web.lihat_sebagai import TINGKAT, boleh_menyamar, peran_efektif


def test_tak_pernah_naik():
    assert peran_efektif("operator", "superadmin") == "operator"
    assert peran_efektif("operator", "admin") == "operator"
    assert peran_efektif("admin", "superadmin") == "admin"
    assert peran_efektif("staff", "admin") == "staff"


def test_boleh_turun():
    assert peran_efektif("superadmin", "operator") == "operator"
    assert peran_efektif("superadmin", "admin") == "admin"
    assert peran_efektif("admin", "operator") == "operator"


def test_peran_sendiri_dan_nilai_ngawur():
    assert peran_efektif("superadmin", "superadmin") == "superadmin"
    for ngawur in ("", None, "dewa", "ADMIN; DROP TABLE users", "  "):
        assert peran_efektif("admin", ngawur) == "admin", ngawur


def test_tahan_spasi_dan_huruf_besar():
    assert peran_efektif("SuperAdmin", " OPERATOR ") == "operator"


def test_operator_tak_bisa_menyamar():
    assert not boleh_menyamar("operator")
    assert not boleh_menyamar(None)
    assert boleh_menyamar("admin") and boleh_menyamar("superadmin")


def test_superadmin_di_puncak_tangga():
    assert TINGKAT["superadmin"] > TINGKAT["admin"] > TINGKAT["operator"]


def test_pemilih_memuat_akun_dulu():
    """Tanpa `butuh_akun`, `request.state.peran_asli` selalu None, izinnya
    selalu gagal, dan kukinya tak pernah terpasang — gagal DIAM-DIAM, tanpa
    satu galat pun. Persis yang terjadi pada percobaan pertama."""
    from app.web import lihat_sebagai

    assert "butuh_akun" in inspect.getsource(lihat_sebagai.pilih)


def test_jalan_pulang_tak_menuntut_peran():
    """Yang menyamar sebagai operator sudah kehilangan hak admin. Jalan pulang
    yang menuntut hak itu adalah pintu yang terkunci dari dalam."""
    from app.web import lihat_sebagai

    from tests.bantu import kode_saja

    assert "boleh_menyamar" not in kode_saja(lihat_sebagai.selesai)
