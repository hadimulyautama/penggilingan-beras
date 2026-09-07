"""Uji integrasi bobot — timbangan yang menimbang, timbangan pula yang membetulkan.

Berat gabah bukan milik produksi. Ia disalin dari tiket timbang, dan salinan
yang tak pernah dibaca ulang adalah cara paling umum dua aplikasi mulai
berbeda tanpa ada yang menyadarinya.
"""
from __future__ import annotations

import inspect

from app.penggilingan.gudang1.services import milling, sinkron_bobot, timbang_link
from tests.bantu import kode_saja


def test_bobot_ikut_walau_sedang_diproses():
    """Justru muatan yang sedang dikerjakan yang paling sering direvisi
    notanya. Dulu batch di dryer, di silo, dan pada giling berjalan sama-sama
    terhalang — dan revisinya tak pernah sampai."""
    sql = timbang_link._SQL_RESINKRON
    for keadaan in ("di_dryer", "di_silo", "dikeringkan"):
        assert keadaan not in sql, f"{keadaan} tak boleh membekukan bobot"


def test_dua_hal_yang_membekukan_bobot():
    """Keduanya berarti 'sudah terlanjur dipakai': ada rupiah berdiri di
    atasnya, atau gabahnya sudah tergiling."""
    sql = timbang_link._SQL_RESINKRON
    assert "b.flag_unverified = true" in sql
    sumber = kode_saja(timbang_link.resinkron_bobot_berubah)
    assert "status_batch <> 'digiling'" in sumber


def test_bahan_giling_berjalan_ikut_disamakan():
    """`berat_gabah_masuk_kg` adalah penyebut rendemen. Bahan yang tercatat
    lebih kecil daripada yang sungguh masuk membuat rendemen terbaca melambung
    — dan yang melihatnya akan mencari sebabnya di mesin, bukan di catatan."""
    sumber = kode_saja(milling.resinkron_bahan_berjalan)
    assert "MillingProcessSource" in sumber
    assert "berat_gabah_masuk_kg" in sumber
    assert "_storage_kg" in sumber


def test_giling_yang_sudah_ditutup_tidak_ditulis_ulang():
    """Angkanya sudah masuk laporan dan sudah dipakai orang lain memutuskan —
    alasan yang sama dengan batas 48 jam pada pembatalan."""
    sumber = kode_saja(milling.resinkron_bahan_berjalan)
    assert "MillingProcess.status == 'proses'" in sumber


def test_perubahannya_meninggalkan_jejak():
    """Angka yang berubah sendiri tanpa jejak adalah angka yang tak bisa
    dipertanggungjawabkan saat ditanya."""
    sumber = kode_saja(milling.resinkron_bahan_berjalan)
    assert "log_activity" in sumber
    assert "direvisi di aplikasi timbangan" in inspect.getsource(
        milling.resinkron_bahan_berjalan)


def test_poller_menjalankan_ketiga_langkahnya():
    """Langkah 2 saja tak cukup: cuplikan bahan giling diambil saat giling
    dimulai, dan ia tak pernah membaca ulang dirinya sendiri."""
    sumber = kode_saja(sinkron_bobot.run_sinkron_bobot_poller)
    for langkah in ("sinkron_bobot_menunggu", "resinkron_bobot_berubah",
                    "resinkron_bahan_berjalan"):
        assert langkah in sumber, langkah


def test_idempoten():
    """Dijalankan tiap tiga menit — putaran kedua tak boleh menulis apa pun
    bila tak ada yang berubah."""
    assert "IS DISTINCT FROM" in timbang_link._SQL_RESINKRON
    sumber = kode_saja(milling.resinkron_bahan_berjalan)
    assert "if berubah:" in sumber, "commit hanya bila memang ada yang berubah"
