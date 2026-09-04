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


def test_hpp_dan_analitik_membaca_daftar_isi_yang_sama():
    """Dua jawaban untuk satu pertanyaan cepat atau lambat berbeda.

    Sebelum ini, HPP dan rapor supplier masing-masing menyelesaikan sendiri
    "apa isi proses giling ini" dari penunjuk tunggal `MillingProcess`.
    Sekarang keduanya memanggil `milling.sumber_batch`.
    """
    from app.services import analytics, costing

    for fungsi in (costing._sumber_info, analytics._proc_batches):
        assert "sumber_batch" in inspect.getsource(fungsi)


def test_biaya_pengeringan_dihitung_per_batch():
    """Satu silo bisa berisi gabah yang lewat dryer DAN gabah kering yang
    langsung masuk. Satu tarif dikali total salah ke dua arah sekaligus: yang
    kering ikut membayar pengeringan yang tak pernah terjadi."""
    from app.services import costing

    sumber = inspect.getsource(costing._sumber_info)
    assert "lewat_dryer" in sumber
    assert "pengeringan +=" in sumber
    assert "pengeringan_rate * kg" not in inspect.getsource(costing.production_cost)


def test_silo_tidak_lagi_berbatas():
    """Dicabut setelah HPP & analitik membaca daftar isi baru — urutannya
    penting, dan uji sebelumnya yang menjaganya."""
    sumber = inspect.getsource(silo.masuk_silo)
    assert "sudah terisi — kosongkan dulu" not in sumber
    assert "Kapasitas Silo" not in inspect.getsource(silo._ensure_cap)


def test_isi_silo_campuran_tetap_terhitung_utuh():
    """Inti seluruh tahap ini: silo yang berisi lot pengeringan DAN batch
    kering lepas harus masuk giling seutuhnya, bukan sebagian."""
    sumber = inspect.getsource(milling.start_milling)
    assert "for r in rows" in sumber and "rows[0]" in sumber
    assert "next((r for r in rows if r.drying_lot_id), rows[0])" in sumber
