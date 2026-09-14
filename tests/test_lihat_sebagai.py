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
    assert peran_efektif("admin", "superadmin") == "admin"


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


def test_operator_boleh_berpindah_gudang():
    """Pemilik 13 Sep 2026: operator saling menggantikan antar gudang —
    berpindah GUDANG boleh, menyamar PERAN tidak."""
    from hmu_identitas.peran import boleh_ganti_gudang

    assert boleh_ganti_gudang("operator") and boleh_ganti_gudang("admin")
    assert not boleh_ganti_gudang(None)
    assert peran_efektif("operator", "operator:g2") == "operator"
    assert peran_efektif("operator", "admin") == "operator"


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


def test_operator_selalu_menyebut_gudang():
    """Operator tanpa gudang adalah orang yang tak berhak apa-apa.

    Pemilik menemukannya di layar: akun admin tak punya gudang default (memang
    tak perlu), jadi samaran "operator" mewarisi ketiadaan itu dan layar Catat
    tampil KOSONG — "Tidak ada aksi untuk peran Anda". Bukan gambaran operator
    mana pun yang sungguh ada di pabrik.
    """
    from app.web.lihat_sebagai import GUDANG, PILIHAN

    kode = [k for k, _ in PILIHAN]
    assert "operator" not in kode, "operator polos tak boleh bisa dipilih"
    assert "operator:g1" in kode and "operator:g2" in kode
    assert set(GUDANG) == {"g1", "g2"}


def test_urai_memisahkan_gudang():
    from app.web.lihat_sebagai import urai

    assert urai("operator:g1") == ("operator", "g1")
    assert urai("operator:g9") == ("operator", None)      # gudang ngawur diabaikan
    assert urai("admin") == ("admin", None)
    assert urai(None) == ("", None)


def test_penjepitan_tetap_berlaku_dengan_gudang():
    """Menempelkan gudang tak boleh jadi celah menaikkan peran."""
    from app.web.lihat_sebagai import peran_efektif

    assert peran_efektif("operator", "admin:g1") == "operator"
    assert peran_efektif("admin", "superadmin:g1") == "admin"
    assert peran_efektif("superadmin", "operator:g1") == "operator"


def test_gudang_ikut_disamarkan():
    """Tanpa menimpa gudang default, samarannya memakai gudang si penyamar —
    dan admin biasanya tak punya."""
    from app.web import security
    from tests.bantu import kode_saja

    kode = kode_saja(security.akun_opsional)
    assert "default_warehouse_id" in kode
