"""Uji skema modul Timbangan.

Dua hal dijaga di sini:

  1. Migrasi 0022 dan model SQLAlchemy tetap sepadan — kolom demi kolom.
     Tanpa uji ini, menambah kolom di model tanpa menambahnya di migrasi baru
     ketahuan saat deploy ke Railway.
  2. Tidak ada kolom harga atau nilai uang di tabel `timbangan_*`. Aturan
     "operator pos timbang tidak boleh tahu harga" ditegakkan oleh ketiadaan
     kolom; uji ini yang menahannya agar tidak diam-diam ditambahkan kembali.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.gudang1.models  # noqa: F401  (daftarkan purchase_batches)
import app.gudang2.models  # noqa: F401  (daftarkan pk_purchase_batches)
import app.models  # noqa: F401  (daftarkan users & suppliers)
from app.database import Base
from app.timbangan import models as M  # noqa: F401

AKAR = pathlib.Path(__file__).resolve().parents[2]
MIGRASI = (
    AKAR / "migrations" / "versions" / "0022_timbangan.py",
    AKAR / "migrations" / "versions" / "0023_timbangan_config.py",
)

# Kata yang tidak boleh muncul sebagai nama kolom di modul ini.
KATA_UANG = (
    "harga", "price", "rupiah", "nilai_rp", "biaya", "total_bayar",
    "potongan", "refaksi", "amount", "tarif",
)


def tabel_model() -> list[str]:
    return sorted(t for t in Base.metadata.tables if t.startswith("timbangan_"))


@pytest.fixture(scope="module")
def kolom_migrasi() -> dict[str, set[str]]:
    """Jalankan seluruh migrasi modul di SQLite sementara, di atas induk tiruan."""
    modul = []
    for berkas in MIGRASI:
        spec = importlib.util.spec_from_file_location(berkas.stem, berkas)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        modul.append(m)

    mesin = sa.create_engine("sqlite://")
    with mesin.begin() as conn:
        for induk in ("users", "suppliers", "purchase_batches", "pk_purchase_batches"):
            conn.exec_driver_sql(f"CREATE TABLE {induk} (id INTEGER PRIMARY KEY)")

        with Operations.context(MigrationContext.configure(conn)):
            for m in modul:
                m.upgrade()

        pemeriksa = sa.inspect(conn)
        return {
            nama: {k["name"] for k in pemeriksa.get_columns(nama)}
            for nama in pemeriksa.get_table_names()
            if nama.startswith("timbangan_")
        }


def test_migrasi_membuat_semua_tabel_model(kolom_migrasi):
    assert sorted(kolom_migrasi) == tabel_model()
    assert len(kolom_migrasi) == 13


@pytest.mark.parametrize("nama", tabel_model())
def test_kolom_migrasi_sama_dengan_model(nama, kolom_migrasi):
    assert kolom_migrasi[nama] == set(Base.metadata.tables[nama].columns.keys())


@pytest.mark.parametrize("nama", tabel_model())
def test_tidak_ada_kolom_uang(nama):
    """Kerahasiaan harga diwujudkan lewat rancangan, bukan penyembunyian."""
    melanggar = [
        kolom for kolom in Base.metadata.tables[nama].columns.keys()
        if any(kata in kolom.lower() for kata in KATA_UANG)
    ]
    assert not melanggar, f"{nama} memuat kolom bernuansa uang: {melanggar}"


def test_transaksi_menyimpan_kedua_petugas():
    """Timbang pertama & kedua bisa dilakukan orang berbeda — keduanya tercatat."""
    kolom = Base.metadata.tables["timbangan_transaksi"].columns.keys()
    assert "timbang1_petugas_id" in kolom
    assert "timbang2_petugas_id" in kolom
    assert "timbang1_waktu" in kolom and "timbang1_waktu_sistem" in kolom
    assert "timbang2_waktu" in kolom and "timbang2_waktu_sistem" in kolom


def test_jembatan_integrasi_disiapkan_kosong():
    kolom = Base.metadata.tables["timbangan_transaksi"].columns
    assert kolom["purchase_batch_id"].nullable
    assert kolom["pk_purchase_batch_id"].nullable
