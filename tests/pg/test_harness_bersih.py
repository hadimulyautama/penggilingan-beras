"""Harness-nya sendiri yang diuji di sini: tiap uji dimulai dari basis data
kosong, apa pun yang terjadi pada lintasan sebelumnya.

Dulu tidak. `pg` mengosongkan tabel SESUDAH tiap uji, jadi uji PERTAMA sebuah
lintasan mewarisi isi lintasan sebelumnya — yang dihentikan di tengah, yang
gagal, atau yang dijalankan dengan env lain. Akibatnya kegagalan yang datang dan
pergi: 23 September 2026 satu baris pemasok sisa menjatuhkan
`test_acuan_hanya_nama_daftar_mingguan`, dan lintasan berikutnya hijau. Kegagalan
seperti itu menuntun orang menyalahkan ujinya, bukan harness-nya — dan uji yang
"kadang gagal" adalah uji yang cepat atau lambat dimatikan. Temuan QA 24 Sep 2026.
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

AKAR = pathlib.Path(__file__).resolve().parents[2]


async def test_basis_data_kosong_saat_uji_mulai(pg):
    """Uji ini SENGAJA meninggalkan baris. Pasangannya di bawah membuktikan
    baris itu tak sampai ke uji berikutnya."""
    from app.models import Supplier

    async with pg() as db:
        assert (await db.execute(select(func.count(Supplier.id)))).scalar_one() == 0
        db.add(Supplier(nama_supplier="Sisa Uji Sebelumnya"))
        await db.commit()


async def test_baris_uji_sebelumnya_tak_terwaris(pg):
    """Urutannya diandalkan: pytest menjalankan berkas ini dari atas ke bawah,
    jadi uji di atas sudah menanam barisnya."""
    from app.models import Supplier

    async with pg() as db:
        assert (await db.execute(select(func.count(Supplier.id)))).scalar_one() == 0


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_dikosongkan_sebelum_yield_bukan_sesudah():
    """Dijaga di tingkat sumber juga: pasangan uji di atas hanya membuktikan
    keadaan ANTAR uji, dan itu tetap benar walau pengosongannya dipindah balik
    ke `finally` — yang justru meninggalkan lubang di uji PERTAMA, tempat tak
    ada uji sebelumnya yang bisa membersihkannya.
    """
    isi = (AKAR / "tests/pg/conftest.py").read_text()
    sebelum = isi.index("sa_text(_KOSONGKAN)")
    yield_ = isi.index("yield Sesi")
    assert sebelum < yield_, "pengosongan kembali ke sesudah uji — lubang warisan terbuka lagi"
    # Dan hanya SEKALI: dua pengosongan berarti separuh waktu uji dipakai
    # mengosongkan tabel yang sudah kosong.
    assert isi.count("sa_text(_KOSONGKAN)") == 1
