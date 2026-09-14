"""`/api/acuan` — daftar acuan yang boleh dilihat ponsel saat sinyal hilang.

Persetujuan pemilik 14 Sep 2026 atas usulan Tahap A: HANYA daftar yang
berubah mingguan — nama pemasok & pelanggan, jenis barang & kondisi gabah,
nama silo & pengering. Tidak ada isi silo, antrean, stok, atau apa pun yang
berubah tiap jam. Nama saja, bukan angka.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio


async def _sesi(pg) -> httpx.AsyncClient:
    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama="Uji", role="operator", status="aktif")
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username="uji", password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan("operator"))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


async def test_acuan_hanya_nama_daftar_mingguan(pg):
    from datetime import datetime, timezone

    from app.models import Dryer, Pelanggan, Silo, Supplier, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        db.add(g1)
        await db.flush()
        db.add_all([
            Supplier(nama_supplier="Pak Tani"),
            Supplier(nama_supplier="Bekas", deleted_at=datetime.now(timezone.utc)),
            Pelanggan(nama_pelanggan="Toko Beras Jaya"),
            Silo(nama_silo="Silo A", warehouse_id=g1.id),
            Dryer(nama="Dryer 1", warehouse_id=g1.id, kapasitas_kg=20000),
        ])
        await db.commit()

    c = await _sesi(pg)
    async with c:
        r = await c.get("/api/acuan")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["pukul"] and len(j["pukul"]) == 5
    daftar = {d["judul"]: d["isi"] for d in j["daftar"]}
    assert daftar["Pemasok"] == ["Pak Tani"], "pemasok terhapus ikut"
    assert daftar["Pelanggan"] == ["Toko Beras Jaya"]
    assert "Gabah basah" in daftar["Jenis barang"] and "Gabah kering" in daftar["Jenis barang"]
    assert daftar["Silo"] == ["Gudang 1 · Silo A"]
    assert daftar["Pengering"] == ["Gudang 1 · Dryer 1"]
    # Nama saja — tak ada angka stok/isi yang ikut terbawa ke ponsel.
    for isi in daftar.values():
        assert all(isinstance(x, str) for x in isi)
    assert set(j) == {"pukul", "daftar"}


async def test_acuan_butuh_sesi(pg):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji") as c:
        assert (await c.get("/api/acuan")).status_code == 401
