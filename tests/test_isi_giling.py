"""Uji pemisahan lot: proses giling punya daftar isinya sendiri (Fase B).

`drying_lots` berarti satu PROSES PENGERINGAN. Apa yang digiling bersama
adalah hal lain, dan sejak migrasi 0031 ia didaftar di
`milling_process_sources` — satu baris per sumber.

Yang dijaga di sini adalah urutan pekerjaannya. Selama satu silo hanya boleh
berisi satu hal, penunjuk tunggal di `MillingProcess` masih benar. Begitu
aturan itu dicabut, siapa pun yang masih membaca penunjuk tunggal akan
menghitung sebagian isi saja — dan pada HPP, "sebagian" berarti angka uang
yang salah tanpa ada yang tahu.
"""
from __future__ import annotations

import inspect

from app.models import MillingProcessSource
from app.penggilingan.gudang1.services import milling, silo


def test_giling_mendaftar_seluruh_isi_silo():
    """Bukan satu baris saja — kalau silo berisi lot DAN batch lepas,
    keduanya ikut tercatat."""
    sumber = inspect.getsource(milling.start_milling)
    assert "berat_per_baris" in sumber
    assert "MillingProcessSource" in sumber
    assert "for r in rows" in sumber


def test_giling_tak_lagi_mengarang_lot_pengeringan():
    """Dulu batch kering yang tak pernah masuk dryer dibuatkan `DryingLot`
    palsu saat giling — waktu mulai = waktu selesai = sekarang, tanpa dryer.
    Lot semacam itu mengotori setiap analisa pengeringan."""
    sumber = inspect.getsource(milling.start_milling)
    assert "next_drying_lot_code" not in sumber


def test_berat_disalin_saat_giling_bukan_dihitung_ulang():
    """Isi silo berubah setelah giling dimulai; berapa yang MASUK ke mesin
    tidak boleh ikut berubah bersamanya."""
    assert "berat_kg" in {c.name for c in MillingProcessSource.__table__.columns}
    assert "berat_kg=kg" in inspect.getsource(milling.start_milling)


def test_satu_baris_silo_tak_bisa_masuk_dua_kali():
    uq = [c for c in MillingProcessSource.__table__.constraints
          if getattr(c, "name", "") == "uq_mps_proses_silo"]
    assert uq, "tanpa ini, satu baris silo bisa terhitung ganda"


def test_aturan_silo_harus_kosong_MASIH_berlaku():
    """PENJAGA URUTAN, bukan penjaga aturan.

    Aturan ini akan dicabut — Direksi sudah memutuskan silo tak berbatas.
    Tetapi mencabutnya SEBELUM HPP dan analitik membaca daftar isi baru akan
    membuat gabah tergiling tanpa masuk hitungan biaya. Uji ini gagal begitu
    ada yang mencabutnya, dan kegagalannya adalah pengingat urutan itu.
    """
    assert "sudah terisi — kosongkan dulu" in inspect.getsource(silo.masuk_silo), (
        "Aturan 'silo harus kosong' dicabut. Sebelum ini sah, "
        "app/services/costing.py dan analytics.py harus membaca "
        "milling_process_sources, bukan proc.drying_lot_id saja."
    )
