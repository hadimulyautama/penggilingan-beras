"""Uji aturan dryer — empat aturan yang ditegaskan Direksi 2 September 2026.

Aturan-aturan ini menentukan kapan gabah boleh masuk mesin pengering. Salah
satu saja longgar, dan dua muatan gabah bisa tercampur di satu mesin tanpa ada
yang menyadarinya sampai hasil gilingnya aneh.
"""
from __future__ import annotations

import inspect

from app.penggilingan.gudang1.services import drying


def test_lot_yang_mengering_maupun_mendinginkan_menutup_dryer():
    """Aturan 1: selagi mengering ATAU mendinginkan, tak ada gabah yang boleh
    masuk."""
    sumber = inspect.getsource(drying.active_drying_lot)
    assert 'DryingLot.status.in_(["proses", "selesai"])' in sumber


def test_lot_yang_belum_pindah_silo_tetap_menutup_dryer():
    """Aturan 2: sudah selesai dikeringkan DAN didinginkan pun, selama gabahnya
    masih menumpuk di dryer, dryer tetap tertutup. Inilah sebab syarat
    `belum_ke_silo` — tanpa itu, gabah baru masuk menimpa yang lama."""
    sumber = inspect.getsource(drying.active_drying_lot)
    assert "belum_ke_silo" in sumber
    assert "SiloStorage.drying_lot_id" in sumber


def test_masuk_dryer_menolak_saat_dryer_terisi():
    sumber = inspect.getsource(drying.masuk_dryer)
    assert "active_drying_lot" in sumber
    assert "masih dipakai lot" in sumber


def test_pendinginan_boleh_dinyatakan_berkali_kali():
    """Aturan 3: gabah yang sudah dinyatakan dingin bisa ternyata masih panas.
    Menolak pernyataan kedua memaksa operator berbohong pada catatan."""
    sumber = inspect.getsource(drying.finish_cooling)
    assert "sudah dinyatakan selesai pendinginan" not in sumber, \
        "penolakan pernyataan kedua seharusnya sudah dicabut"
    assert "diulang" in sumber, "putaran ulang harus terbaca di riwayat"


def test_basah_dan_kering_tak_boleh_bercampur_di_dryer():
    """Bukan bagian dari empat aturan itu, tetapi menjaga keempatnya berguna:
    dryer yang menerima campuran membuat kadar air lot tak berarti apa-apa."""
    assert "mencampur gabah basah & kering" in inspect.getsource(drying.masuk_dryer)


def test_pengeringan_satu_batch_diperingatkan_bukan_ditolak():
    """Dryer 30 ton yang dinyalakan untuk satu muatan kecil membakar bahan
    bakar yang sama dengan yang penuh, dan biayanya dibagi ke gabah yang lebih
    sedikit. Tetapi menahan gabah demi menunggu muatan kedua justru membuatnya
    menginap — jadi peringatan, bukan penolakan."""
    sumber = inspect.getsource(drying.start_drying)
    assert "len(loose) < 2" in sumber
    assert "peringatan" in sumber
    assert "raise DryingError" not in sumber.split("peringatan = None")[1]


def test_silo_campuran_diperingatkan_bukan_ditolak():
    """Gabahnya harus keluar dari dryer, dan menahannya sampai silo kosong
    memacetkan pengeringan berikutnya. Tetapi isinya jadi campuran, dan itu
    harus terbaca sekarang — bukan diketahui belakangan saat angka giling
    tidak seperti yang diingat orang."""
    from app.penggilingan.gudang1.services import silo
    from app.web import miniapp

    assert "digabung = await _silo_content_kg" in inspect.getsource(silo.masuk_silo)
    assert "isinya kini tercampur" in inspect.getsource(miniapp.act_pindah_silo)


# ─────────────── Tiap dryer berjalan sendiri-sendiri ───────────────

def test_keterisian_ditanyakan_per_mesin():
    """Aturan 1 & 2 kini berlaku per mesin. Menanyakan 'apakah dryer terpakai'
    tanpa menyebut mesinnya akan menutup seluruh pabrik gara-gara satu mesin
    sibuk."""
    sumber = inspect.getsource(drying.active_drying_lot)
    assert "dryer_id" in sumber
    assert "DryingLot.dryer_id == dryer_id" in sumber


def test_gabah_menunggu_disaring_per_mesin():
    """Tanpa saringan ini, 'mulai pengeringan' menyapu gabah dari SEMUA mesin
    ke dalam satu lot — gabah yang tidak pernah bertemu di mesin yang sama."""
    assert "PurchaseBatch.dryer_id == dryer_id" in inspect.getsource(
        drying._loose_dryer_batches)


def test_masuk_dan_mulai_keduanya_menyebut_mesin():
    for fungsi in (drying.masuk_dryer, drying.start_drying):
        assert "pilih_dryer" in inspect.getsource(fungsi)


def test_satu_mesin_tak_perlu_dipilih():
    """Menyuruh orang memilih dari daftar berisi satu pilihan bukan ketelitian,
    melainkan pekerjaan tambahan tanpa isi."""
    sumber = inspect.getsource(drying.pilih_dryer)
    assert "if len(mesin) == 1" in sumber


def test_mesin_batch_dilepas_saat_lot_terbentuk():
    """Setelah lot ada, mesinnya tersimpan di lot. Dua tempat yang menyebut
    hal yang sama cepat atau lambat berbeda."""
    assert "b.dryer_id = None" in inspect.getsource(drying.start_drying)
