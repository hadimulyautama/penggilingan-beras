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


def test_gabah_kering_punya_tiga_jenis_tujuan():
    """Tiga JENIS — dryer, silo, tumpukan. Silo mana disebut terpisah, karena
    jumlahnya bisa bertambah lewat Pengaturan."""
    kering = peta_jenis.intake_dari_jenis("GABAH_KERING")
    assert set(kering.tujuan_pilihan) == {"silo", "dryer", "tumpuk"}


# ─────────────────────── Keluar dari tumpukan ───────────────────────

def test_basah_tak_pernah_boleh_ke_silo():
    """Dari mana pun ia datang — baru turun dari truk atau sedang menumpuk —
    gabah basah belum kering, dan silo Gudang 1 menampung gabah kering."""
    assert set(tumpukan.TUJUAN_PINDAH["basah"]) == {"dryer", "tumpuk"}


def test_kering_boleh_ke_dryer_silo_maupun_tumpukan():
    assert set(tumpukan.TUJUAN_PINDAH["kering"]) == {"dryer", "silo", "tumpuk"}


def test_satu_aksi_untuk_dua_keadaan_yang_menunggu_tempat():
    """Gabah yang sedang menumpuk dan gabah yang penempatannya gagal butuh
    tindakan yang sama. Dua aksi yang mirip hanya memaksa operator menebak
    mana yang berlaku."""
    assert set(tumpukan.MENUNGGU_TEMPAT) == {"baru", "ditumpuk"}
    assert "status_batch.in_(MENUNGGU_TEMPAT)" in inspect.getsource(
        tumpukan.menunggu_tempat)


def test_pemindahan_tak_menyalin_aturan_dryer_dan_silo():
    """Aturan dryer dan aturan silo hidup di layanannya masing-masing.
    Menyalinnya ke sini berarti dua salinan yang suatu hari berbeda — dan yang
    di sini yang akan luput diperbarui."""
    sumber = inspect.getsource(tumpukan.tempatkan)
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


def test_gabah_yang_gagal_ditempatkan_menagih_di_berjalan():
    """Penempatan otomatis bisa gagal — dryer sedang dipakai, misalnya.
    Batch-nya tetap tersimpan (gabahnya sudah turun dari truk) lalu berstatus
    'baru'. Tanpa baris ini, gabah itu berdiri di halaman tanpa ada satu layar
    pun yang menyebutnya."""
    sumber = inspect.getsource(berjalan.untuk_gudang1)
    assert 'status_batch == "baru"' in sumber
    assert "belum ditempatkan" in sumber


def test_komoditas_tiket_dibaca_dari_peta_bukan_ditebak():
    """Taksonomi jenis di Timbangan berbasis data dan bisa bertambah. Menebak
    dari awalan kode berarti komoditas baru diam-diam dianggap gabah kering —
    dan gabah basah yang salah dikenali akan ditawari masuk silo."""
    from app.services import berjalan as brj
    from app.web import miniapp as mn

    for fungsi in (brj._tiket_belum_ditaut, mn.timbang_masuk_aktif):
        sumber = inspect.getsource(fungsi)
        assert "intake_dari_jenis" in sumber
        assert 'startswith("GABAH")' not in sumber


def test_baris_berjalan_membawa_nilainya_ke_lembar_aksi():
    """Barisnya sudah menunjuk satu tiket. Menanyakannya lagi di dalam lembar
    berarti orang memilih hal yang sama dua kali — dan kesempatan kedua itulah
    tempat ia salah pilih."""
    import pathlib

    from app.services.berjalan import Baris

    assert "nilai" in Baris.__dataclass_fields__
    akar = pathlib.Path(__file__).resolve().parents[1]
    html = (akar / "app/web/templates/berjalan.html").read_text()
    assert "&nilai=" in html
    js = (akar / "app/web/static/aksi.js").read_text()
    assert "isiDariBaris" in js


def test_waktu_kedatangan_diambil_dari_tiket_bukan_saat_mengetik():
    """Truk ditimbang saat ia tiba; pencatatannya bisa menyusul berhari-hari
    pada tiket susulan. Memakai jam ketik membuat laporan "jam kedatangan
    gabah" menggambarkan kebiasaan mengetik, bukan kebiasaan truk datang — dan
    atas dasar itulah giliran jaga diatur."""
    from app.penggilingan.gudang1.services import purchase

    sumber = inspect.getsource(purchase.create_purchase_batch_dari_timbang)
    assert 'tiket.get("timbang1_waktu")' in sumber
    # Waktu yang disebut operator sendiri tetap menang atas tiket.
    assert "if tanggal or jam:" in sumber
