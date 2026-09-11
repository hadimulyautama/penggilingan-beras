"""Angka yang mustahil ditolak, dan keadaan fisik yang mustahil dicegah DB.

**P-S-01 & P-K-16.** Server menerima `nan`, `inf`, dan angka negatif apa
adanya. NaN lalu meracuni seluruh hitungan yang menyentuhnya — stok, laporan,
HPP — dan Beranda Gudang 1 menjawab 500 untuk SEMUA view karena `int(NaN)`.
Satu salah ketik tanda minus menghasilkan total harga −70.344.000.

NaN punya sifat yang membuatnya jauh lebih berbahaya daripada angka salah
biasa: ia menular. Setiap penjumlahan yang menyentuhnya jadi NaN, jadi satu
baris rusak membuat seluruh kolom rusak — dan tak ada satu pun pesan.

**P-K-04 … P-K-14.** Tak ada satu pun `FOR UPDATE` di kode. Dua operator yang
bekerja bersamaan bisa membuat keadaan yang mustahil secara fisik: satu lot
masuk dua silo sekaligus, PK luar masuk Gudang 2 dua kali, transfer melebihi
yang diproduksi.
"""
from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.asyncio


# ─────────────────── Angka (P-S-01, P-K-16) ───────────────────

@pytest.mark.parametrize("buruk", [float("nan"), float("inf"), float("-inf"), -5000.0, 0.0])
async def test_model_permintaan_menolak_angka_mustahil(buruk):
    """Ditolak di PINTU, sebelum menyentuh apa pun."""
    from pydantic import ValidationError

    from app.web.miniapp import HasilGilingReq

    with pytest.raises(ValidationError):
        HasilGilingReq(kode_proses="LOT-1", berat_kumulatif=buruk)


async def test_penjaga_layanan_juga_menolak():
    """Pintu Pydantic tak dilewati semua orang: lapisan AI dan rute lain
    memanggil layanannya langsung. Penjaga di layanan yang menutup sisanya."""
    from app.services.angka import AngkaError, angka_wajar

    for buruk in (float("nan"), float("inf"), -1.0, 0.0):
        with pytest.raises(AngkaError):
            angka_wajar(buruk, "berat")
    # Yang wajar lewat, dan kembali sebagai float.
    assert angka_wajar(12.5, "berat") == 12.5


async def test_pesan_galat_menyebut_kolomnya():
    """"Angka tidak valid" tak memberi tahu operator harus memperbaiki apa."""
    from app.services.angka import AngkaError, angka_wajar

    with pytest.raises(AngkaError) as e:
        angka_wajar(float("nan"), "berat hasil giling")
    assert "berat hasil giling" in str(e.value)


async def test_nan_tak_bisa_masuk_lewat_lapisan_layanan():
    """P-K-16: `milling.py` menerima `berat_kumulatif` apa adanya."""
    import inspect

    from app.penggilingan.gudang1.services import milling

    assert "angka_wajar" in inspect.getsource(milling)


# ─────────────────── Constraint (P-K-04 … P-K-13) ───────────────────

async def test_migrasi_memeriksa_data_pelanggar_lebih_dulu(pg):
    """Migrasi yang menambahkan constraint pada data yang sudah melanggar akan
    gagal di tengah deploy, atau — lebih buruk — menggoda orang berikutnya
    untuk menghapus baris yang menghalangi.

    Jadi ia MEMERIKSA lebih dulu dan gagal dengan menyebut baris mana yang
    bermasalah, bukan menghapus atau mengubah apa pun diam-diam.
    """
    import pathlib

    berkas = (pathlib.Path(__file__).resolve().parents[2]
              / "migrations/versions/0040_constraint_fisik.py").read_text()
    assert "DELETE" not in berkas.upper(), "migrasi menghapus data"
    assert "periksa" in berkas.lower() or "pelanggar" in berkas.lower()


@pytest.mark.parametrize("indeks", [
    "uq_pk_gudang2_intakes_batch",
    "uq_pk_gudang2_intakes_transfer",
    "uq_silo_storage_lot_terisi",
    "uq_silo_storage_batch_terisi",
    "uq_drying_lot_batches_batch",
    "uq_milling_process_silo_proses",
])
async def test_indeks_unik_parsial_terpasang(pg, indeks):
    """Satu lot tak boleh berada di dua silo sekaligus; PK luar tak boleh
    masuk dua kali. Basis data yang menolaknya lebih bisa dipercaya daripada
    pemeriksaan di kode, karena ia berlaku juga untuk jalur yang lupa
    memeriksanya."""
    from sqlalchemy import text

    async with pg() as db:
        ada = (await db.execute(text(
            "SELECT count(*) FROM pg_indexes WHERE indexname = :n"
        ), {"n": indeks})).scalar()
    assert ada == 1, f"indeks {indeks} belum ada"


async def test_berat_tak_boleh_nol_atau_negatif_di_db(pg):
    """Lapisan terakhir. Kalau semua penjaga di atasnya luput, basis data
    tetap menolak — dan penolakan basis data tak bisa dilewati jalur baru
    yang lupa memanggil penjaganya."""
    from sqlalchemy import text

    async with pg() as db:
        n = (await db.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname LIKE 'ck_%_berat_positif'"
        ))).scalar()
    assert n >= 1, "tak ada CHECK berat > 0"


# ─────────────────── Kunci baris (P-K-04, P-K-05) ───────────────────

async def test_sumber_daya_dikunci_sebelum_diperiksa():
    """Cek-lalu-tulis tanpa kunci: dua permintaan yang datang bersamaan
    sama-sama lolos pemeriksaan sebelum salah satunya menulis.

    QA mengukur PK luar masuk Gudang 2 dua kali pada 20 dari 20 percobaan.
    """
    import inspect

    from app.penggilingan.gudang1.services import silo
    from app.penggilingan.gudang2 import service as g2

    # Batch PK luar dikunci, dan duplikatnya diperiksa SESUDAH kunci didapat.
    kode = inspect.getsource(g2.masukkan_pk_luar) if hasattr(g2, "masukkan_pk_luar") \
        else inspect.getsource(g2)
    assert "with_for_update()" in kode

    # Lot pengeringan dikunci sebelum dinyatakan masuk silo.
    assert "with_for_update()" in inspect.getsource(silo)
