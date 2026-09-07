"""Uji aturan berhenti sementara — pengeringan & giling.

Mesin berhenti di tengah jalan adalah kejadian sehari-hari, dan sebelum ada
tempat untuk itu operator hanya punya dua pilihan yang sama-sama merusak
catatan: membiarkan prosesnya "berjalan" padahal mesinnya mati, atau
menutupnya lalu memulai proses baru — yang membuat satu muatan gabah
terhitung dua kali.
"""
from __future__ import annotations

import inspect

from app.penggilingan.gudang1.services import jeda
from tests.bantu import kode_saja


def test_jeda_disimpan_sebagai_tabel_bukan_kolom():
    """Satu proses bisa berhenti berkali-kali dalam sehari, dan yang berguna
    justru jumlah PER SEBAB. Kolom pada lot hanya bisa menyimpan yang
    terakhir — dan yang terakhir hampir tak pernah yang terbesar."""
    from app.models import JedaProses

    kolom = {c.name for c in JedaProses.__table__.columns}
    assert {"jenis", "sebab", "mulai", "selesai", "dicatat_oleh"} <= kolom
    assert "drying_lot_id" in kolom and "milling_process_id" in kolom


def test_sebab_wajib_dan_boleh_ditulis_sendiri():
    """Berhenti tanpa sebab tak bisa dipakai memperbaiki apa pun. Tetapi
    daftar sebab tak akan pernah lengkap, dan daftar yang tak lengkap memaksa
    orang memilih yang paling mirip — lalu angkanya berbohong dengan rapi."""
    sumber = kode_saja(jeda.hentikan)
    assert "SEBAB_LAIN" in sumber
    assert "Tulis sebabnya dulu" in inspect.getsource(jeda.hentikan)
    assert "Pilih sebab berhentinya" in inspect.getsource(jeda.hentikan)


def test_dua_jenis_punya_daftar_sebabnya_sendiri():
    """Dryer tak pernah kepenuhan limbah; mesin giling tak pernah kehabisan
    bahan bakar. Daftar gabungan akan memaksa operator melewati sebab yang
    mustahil untuk mesinnya."""
    assert "Bahan bakar habis" in jeda.SEBAB["pengeringan"]
    assert "Bahan bakar habis" not in jeda.SEBAB["giling"]
    assert "Limbah produksi penuh" in jeda.SEBAB["giling"]
    assert "Limbah produksi penuh" not in jeda.SEBAB["pengeringan"]
    # "Mesin rusak" saja ambigu begitu ada mesin pendukung — dan sebab yang
    # ambigu tak bisa dipakai menghitung apa pun.
    for daftar in jeda.SEBAB.values():
        assert "Mesin rusak" not in daftar
        assert "Mesin pendukung rusak" in daftar


def test_tertahan_menghitung_jeda_yang_masih_berlangsung():
    """Proses yang sedang mati tak boleh terlihat seolah jam tertahannya
    berhenti bertambah — justru saat itulah angkanya paling perlu naik."""
    sumber = kode_saja(jeda.tertahan_detik)
    assert "j.selesai or kini" in sumber


def test_tak_bisa_berhenti_dua_kali():
    assert "memang sedang berhenti" in inspect.getsource(jeda.hentikan)


def test_lanjutkan_menolak_yang_tak_sedang_berhenti():
    assert "tidak sedang berhenti" in inspect.getsource(jeda.lanjutkan)


def test_proses_yang_sudah_selesai_tak_bisa_dihentikan():
    """Menghentikan yang sudah ditutup akan menciptakan jam tertahan pada
    proses yang jamnya sudah tidak berjalan."""
    assert "sudah tidak berjalan" in inspect.getsource(jeda._lot_berjalan)
    assert "sudah ditutup" in inspect.getsource(jeda._giling_berjalan)


def test_rekap_dijumlah_per_sebab_terbanyak_dulu():
    """Daftar kejadian cuma bisa dibaca; yang dijumlah per sebab bisa dipakai
    memutuskan — mesin pendukung yang memakan dua jam sehari itu belanja,
    bukan keluhan."""
    sumber = kode_saja(jeda.rekap_berhenti)
    assert "reverse=True" in sumber
    assert "b.detik" in sumber


def test_jeda_tak_bisa_dibatalkan_lewat_undo():
    """Yang benar bukan menghapus catatan berhentinya melainkan MELANJUTKAN
    prosesnya. Berhenti yang dihapus membuat jam berjalan ikut berbohong."""
    from app.services import undo

    # Punya label manusia — supaya riwayat tetap bisa dibaca orang …
    assert undo.label_tabel("jeda_proses") != "jeda_proses"
    # … tetapi TIDAK ada di daftar yang bisa dibatalkan.
    assert "jeda_proses" not in undo._UNDOABLE


def test_layar_berjalan_membedakan_yang_berhenti():
    """Yang sedang berhenti tak menunggu operator — ia menunggu montir. Kalau
    ia terbaca sama dengan yang sedang jalan, tak ada yang akan menelepon
    montirnya."""
    from app.services import berjalan

    sumber = kode_saja(berjalan.untuk_gudang1)
    assert "jeda_terbuka" in sumber
    assert "lanjutkan_proses" in sumber
    assert "hentikan_proses" in sumber


def test_dashboard_menyebut_berapa_lama_pabrik_berhenti():
    from app.services import dashboard

    assert "rekap_berhenti" in kode_saja(dashboard._berhenti_hari_ini)
    assert "Pabrik berhenti" in inspect.getsource(dashboard.render_dashboard_text)


def test_aksi_terdaftar_untuk_gudang1():
    from app.web import miniapp

    assert miniapp._ACTION_WH.get("hentikan_proses") == "g1"
    assert miniapp._ACTION_WH.get("lanjutkan_proses") == "g1"
