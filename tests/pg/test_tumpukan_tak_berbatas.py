"""Tumpukan Gudang 2 tidak berbatas — dan layarnya tak boleh bilang "maks 0 ton".

Keputusan pemilik 12 September 2026: tumpukan Gudang 2 TIDAK berbatas, dan
`g2_tumpukan_maks_kg` bawaannya 0. Nol di situ berarti "tak berbatas", bukan
"kapasitasnya nol".

Tiga pembaca sudah memperlakukannya benar sejak awal (`stok.py`, `beranda.py`,
`layar.py`); baris status di `laporan_stok_gudang2` satu-satunya yang tidak,
dan hasilnya kalimat yang mengaku kapasitasnya nol sambil tumpukannya berisi.

⚠ Yang dijaga di sini TAMPILANNYA, bukan nilainya. Memasang angka pada
`g2_tumpukan_maks_kg` akan membuat uji ini hijau dengan cara yang melanggar
keputusan pemilik ("jangan ada batasan berapa ton").
"""
from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def g2(pg):
    from app.models import Silo, Warehouse
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        from sqlalchemy import select
        gd = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == "g2"))
        assert gd is not None, "seed_master harus menyediakan Gudang 2"
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=gd.id),
                    Silo(nama_silo="Silo B", warehouse_id=gd.id)])
        await db.commit()
        return gd.id


async def test_batas_tak_disetel_tak_disebut_sama_sekali(pg, g2, monkeypatch):
    """"maks 0 ton" adalah layar yang mengatakan kapasitasnya nol padahal
    barangnya berdiri di situ."""
    from app.config import settings
    from app.penggilingan.gudang2.service import laporan_stok_gudang2

    monkeypatch.setattr(settings, "g2_tumpukan_maks_kg", 0)
    async with pg() as db:
        teks = await laporan_stok_gudang2(db, financial=False)
    baris = next(b for b in teks.splitlines() if "Tumpukan" in b)
    assert "maks" not in baris, baris
    assert "0 ton" not in baris, baris


async def test_batas_yang_memang_disetel_tetap_disebut(pg, g2, monkeypatch):
    """Pabrik lain memang menyebut angkanya — pagarnya "nol berarti tak
    berbatas", bukan "jangan pernah menyebut maks"."""
    from app.config import settings
    from app.penggilingan.gudang2.service import laporan_stok_gudang2

    monkeypatch.setattr(settings, "g2_tumpukan_maks_kg", 150_000)
    async with pg() as db:
        teks = await laporan_stok_gudang2(db, financial=False)
    baris = next(b for b in teks.splitlines() if "Tumpukan" in b)
    assert "maks 150 ton" in baris, baris


async def test_batasnya_tetap_tak_disetel_di_berkas_setelan():
    """Yang dibetulkan TAMPILANNYA, bukan nilainya.

    Mengisi `g2_tumpukan_maks_kg` akan membuat uji pertama hijau dengan cara
    yang melanggar keputusan pemilik: "jangan ada batasan berapa ton".
    """
    import inspect

    from app import config

    sumber = inspect.getsource(config)
    assert "g2_tumpukan_maks_kg: int = 0" in sumber, \
        "bawaan batas tumpukan G2 bukan 0 lagi — pemilik memutuskan tak berbatas"
