"""Uji tumpukan gabah (Fase B, tahap 3).

Tumpukan bukan sekadar tempat: Direksi menyebutnya jelas — kalau ada tumpukan,
berarti ada pembelian yang berlebih. Karena itu yang dijaga di sini bukan
hanya "gabah bisa ditaruh", melainkan bahwa keberadaannya TERLIHAT dan bahwa
keluarnya mengikuti kondisi gabahnya.
"""
from __future__ import annotations

import inspect

import pytest

from app.penggilingan import peta_jenis
from app.penggilingan.gudang1.services import tumpukan
from app.services import berjalan
from app.web import miniapp


# ─────────────────────── Tujuan saat gabah masuk ───────────────────────

def test_gabah_basah_tak_lagi_dipaksa_ke_dryer():
    """Dryer hanya menerima satu lot pada satu waktu. Gabah yang datang saat
    dryer terisi harus mendarat di suatu tempat — memaksanya ke dryer hanya
    membuat pencatatan gagal, bukan membuat gabahnya hilang."""
    basah = peta_jenis.intake_dari_jenis("GABAH_BASAH")
    assert basah.tujuan_wajib is None
    assert set(basah.tujuan_pilihan) == {"dryer", "tumpuk"}


def test_gabah_basah_tetap_tak_boleh_langsung_ke_silo():
    """Silo Gudang 1 menampung gabah KERING. Ini pagar yang tidak boleh ikut
    longgar saat tumpukan ditambahkan."""
    basah = peta_jenis.intake_dari_jenis("GABAH_BASAH")
    assert "silo_a" not in basah.tujuan_pilihan
    assert "silo_b" not in basah.tujuan_pilihan


def test_gabah_kering_punya_empat_tujuan():
    kering = peta_jenis.intake_dari_jenis("GABAH_KERING")
    assert set(kering.tujuan_pilihan) == {"silo_a", "silo_b", "dryer", "tumpuk"}


# ─────────────────────── Keluar dari tumpukan ───────────────────────

def test_basah_hanya_boleh_keluar_ke_dryer():
    assert tumpukan.TUJUAN_PINDAH["basah"] == ("dryer",)


def test_kering_boleh_ke_dryer_maupun_silo():
    assert set(tumpukan.TUJUAN_PINDAH["kering"]) == {"dryer", "silo_a", "silo_b"}


def test_pemindahan_tak_menyalin_aturan_dryer_dan_silo():
    """Aturan dryer dan aturan silo hidup di layanannya masing-masing.
    Menyalinnya ke sini berarti dua salinan yang suatu hari berbeda — dan yang
    di sini yang akan luput diperbarui."""
    sumber = inspect.getsource(tumpukan.pindah)
    assert "masuk_dryer" in sumber and "masuk_silo" in sumber
    assert "status ==" not in sumber, "jangan menegakkan ulang aturan dryer/silo"


# ─────────────────────── Tumpukan mana: tidak disimpan ───────────────────────

def test_tumpukan_mana_diturunkan_dari_kondisi_bukan_disimpan():
    """Dua tumpukan, tetapi tidak ada kolom yang menyebut yang mana. Kondisi
    gabah sudah tercatat di batch; menyimpannya lagi berarti dua tempat yang
    suatu hari berbeda, dan tak ada yang tahu mana yang benar."""
    from app.models import PurchaseBatch

    kolom = {c.name for c in PurchaseBatch.__table__.columns}
    assert not any("tumpuk" in k for k in kolom)
    assert "kondisi_gabah" in kolom


def test_memakai_kosakata_status_yang_sudah_ada():
    """PK di Gudang 2 sudah memakai 'ditumpuk'. Satu kata untuk satu keadaan,
    di kedua gudang."""
    assert tumpukan.DITUMPUK == "ditumpuk"


# ─────────────────────── Terlihat, bukan tersembunyi ───────────────────────

def test_isi_tumpukan_muncul_sebagai_pekerjaan_yang_menunggu():
    """Kalau tumpukan hanya jadi tempat penyimpanan yang tenang, gabah bisa
    menumpuk berminggu-minggu tanpa ada yang menagih."""
    sumber = inspect.getsource(berjalan.untuk_gudang1)
    assert "tumpukan" in sumber
    assert 'aksi="pindah_tumpukan"' in sumber


def test_aksi_pindah_tumpukan_terdaftar_dan_dipetakan():
    assert "pindah_tumpukan" in miniapp._ACTION_WH
