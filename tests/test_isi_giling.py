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

from tests.bantu import kode_saja

from app.models import MillingProcessSource
from app.penggilingan.gudang1.services import milling, silo


def test_giling_mendaftar_seluruh_isi_silo():
    """Bukan satu baris saja — kalau silo berisi lot DAN batch lepas,
    keduanya ikut tercatat."""
    sumber = inspect.getsource(milling.start_milling)
    # Tiap baris dibaca berikut KEPASTIAN bobotnya sejak QA P6 (21 Sep 2026).
    assert "bobot_per_baris" in sumber
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
    # `bb.kg` = angka bila diketahui, NULL bila belum — tetap cuplikan saat
    # mulai, bukan dihitung ulang (QA P6-01).
    assert "berat_kg=bb.kg" in inspect.getsource(milling.start_milling)


def test_satu_baris_silo_tak_bisa_masuk_dua_kali():
    uq = [c for c in MillingProcessSource.__table__.constraints
          if getattr(c, "name", "") == "uq_mps_proses_silo"]
    assert uq, "tanpa ini, satu baris silo bisa terhitung ganda"


def test_rapor_supplier_membaca_daftar_isi_yang_sama():
    """Dua jawaban untuk satu pertanyaan cepat atau lambat berbeda.

    Dulu HPP dan rapor supplier masing-masing menyelesaikan sendiri "apa isi
    proses giling ini" dari penunjuk tunggal `MillingProcess`; keduanya
    dipindahkan ke `milling.sumber_batch`.

    HPP-nya sendiri DIBUANG 28 September 2026 bersama seluruh harga (keputusan
    pemilik), jadi yang tersisa dijaga sendirian — dan ia masih perlu dijaga:
    rapor supplier membagi rendemen menurut porsi berat tiap batch, dan porsi
    yang dihitung dari penunjuk tunggal akan menyebut satu supplier saja untuk
    lot yang isinya campuran.

    Uji kembarannya, `test_biaya_pengeringan_dihitung_per_batch`, ikut dibuang:
    seluruh subjeknya (`costing._sumber_info`) sudah tidak ada.
    """
    from app.services import analytics

    assert "sumber_batch" in inspect.getsource(analytics._proc_batches)


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


def test_laporan_supplier_tak_membaca_penunjuk_tunggal():
    """Laporan dulu menyebut supplier lewat `proc.drying_lot_id`.

    Selama satu silo hanya berisi satu hal, itu benar. Begitu silo boleh
    dicampur, penunjuk itu menyebut sumber pertama dan mendiamkan sisanya:
    silo berisi pengeringan DAN gabah kering langsung melaporkan supplier yang
    pertama saja. Yang kedua hilang dari laporan tanpa jejak — padahal
    gabahnya ikut tergiling dan ikut dibayar.
    """
    badan = kode_saja(milling._milling_supplier_names)
    assert "sumber_batch" in badan
    assert "proc.drying_lot_id" not in badan
    assert "proc.purchase_batch_id" not in badan


def test_laporan_giling_menyebut_seluruh_asal():
    """"Bahan dari X (via LOT-…)" hanya menyebut satu sumber. Lot yang isinya
    campuran harus menyebut semuanya — itu satu-satunya cara beras PK bisa
    dirunut balik ke gabah siapa."""
    badan = kode_saja(milling.laporan_milling)
    assert "asal_isi" in badan
    assert "via {lot.kode_lot}" not in badan

    asal = kode_saja(milling.asal_isi)
    assert "MillingProcessSource" in asal
    assert "kode_batch" in asal


def test_tumpukan_pk_gudang1_memperingatkan_bukan_menolak():
    """PK yang sudah keluar dari mesin sudah ada secara fisik.

    Menolak mencatatnya tidak membuatnya lenyap — ia hanya membuat catatan
    berbohong, dan justru menyembunyikan keadaan yang paling perlu dilihat:
    lantai penuh. Beda dengan tumpukan Gudang 2 yang MENOLAK, karena di sana
    yang dijaga adalah keputusan penempatan, dan keputusan masih bisa
    dialihkan ke silo.
    """
    badan = kode_saja(milling.log_progress)
    assert "g1_pk_tumpukan_maks_kg" in badan
    assert "peringatan" in badan
    # Tak boleh ada penolakan yang dipicu batas lantai.
    assert "raise MillingError" not in badan.split("stok_pk_g1")[-1]


def test_stok_pk_gudang1_diturunkan_bukan_disimpan():
    """"Ditumpuk" vs "langsung dibawa ke penyosohan" bukan dua keadaan yang
    perlu dinyatakan operator: yang membedakannya hanya ada tidaknya transfer,
    dan itu sudah tercatat. Dua sumber untuk satu fakta pasti berselisih, dan
    yang salah selalu yang diketik manual."""
    # Turunannya kini tinggal di `stok_pk_g1_pemilik` — SATU lintasan yang
    # memecah (pabrik, titipan) sekaligus, karena Beranda butuh keduanya
    # berdampingan. Aturannya tak bergeser, tempatnya saja; jadi yang diperiksa
    # keduanya: yang menurunkan wajib membaca rinciannya, dan yang dipanggil
    # orang wajib menurunkan dari situ — bukan menghitung sendiri untuk kedua
    # kalinya.
    badan = kode_saja(milling.stok_pk_g1_pemilik)
    assert "_pk_breakdown" in badan
    assert "stok_pk_g1_pemilik" in kode_saja(milling.stok_pk_g1)
    # Bukan dibaca dari tabel keadaan tersendiri.
    for b in (badan, kode_saja(milling.stok_pk_g1)):
        assert "PkStockGudang1" not in b
        assert "MillingPkRouting" not in b


def test_tumpukan_pk_tak_hilang_saat_sisanya_kosong():
    """Laporan Status Gudang 1 dulu berhenti lebih awal kalau dryer & silo
    kosong dan tak ada giling berjalan — padahal PK bisa sedang menumpuk di
    lantai. Akibatnya terbalik dari yang dibutuhkan: tumpukan menghilang dari
    layar tepat ketika ia SATU-SATUNYA hal yang tersisa untuk dikerjakan."""
    from app.services import report
    badan = kode_saja(report.status_gudang1)
    assert "stok_pk_g1" in badan
    assert "pk_menumpuk <= 0" in badan
