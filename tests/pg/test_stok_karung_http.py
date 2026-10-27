"""`/stok-karung` & `/stok-karung-jasa` lewat HTTP sungguhan — Postgres.

Keputusan pemilik 7 Oktober 2026, dengan koreksi susulan hari yang sama:
tujuan "Pindah kepemilikan karung" adalah KONTAK pelanggan (`pelanggan-
kledo`), BUKAN pesanan jasa (`jasa-berjalan`) — lihat catatan panjang di
`packaging.pindah_kepemilikan_karung`. Menjaga yang tak terlihat dari uji
service-level (`test_stok_karung_jasa.py`): gerbang peran (operator Gudang 1
ditolak, sama dengan `/stok-produk`), gerbang `can_see_financials` pada aksi
"Pindah kepemilikan karung", dan nilai picker `karung-pabrik-tersedia` yang
WAJIB cocok persis dengan `nilai=` yang akan dikirim tombol kartu.
"""
from __future__ import annotations

from tests.pg.kontak import pelanggan_kledo
from tests.pg.formulir import cap_formulir

from datetime import date

import pytest

from app.database import now_local

pytestmark = pytest.mark.asyncio


async def _klien(pg, *, peran: str = "admin", g1: bool = False) -> "httpx.AsyncClient":
    """Klien HTTP berlogin — sebangun `_klien` di `test_pindah_kepemilikan_produk.py`.

    `g1=True` → operator dengan `default_warehouse_id` Gudang 1 (view
    SELEPAN), dipakai menguji gerbang "layar ini milik Gudang 2"."""
    import httpx

    from app.main import app
    from app.models import ProduksiAkun, User, Warehouse
    from app.services.seed import seed_master
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan
    from sqlalchemy import select

    await seed_master()
    async with pg() as db:
        u = User(nama=f"Uji {peran}", role=peran, status="aktif")
        db.add(u)
        await db.flush()
        if g1:
            g = (await db.execute(select(Warehouse).where(
                Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
            u.default_warehouse_id = g.id
        a = ProduksiAkun(user_id=u.id, username=f"skj{u.id}",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan(peran))
        db.add(a)
        await db.commit()
        tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    t = csrf.terbitkan_baru()
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, t)
    c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
    return c


async def _beli(db, models, *, pemakai_id, lembar, kode):
    from sqlalchemy import select

    mat = (await db.execute(select(models.PackagingMaterial)
                            .where(models.PackagingMaterial.kode == "laminasi"))
           ).scalars().first()
    if mat is None:
        mat = models.PackagingMaterial(kode="laminasi", nama="Karung Laminasi", aktif=True)
        db.add(mat)
        await db.flush()
    size = (await db.execute(select(models.PackageSize)
                             .where(models.PackageSize.ukuran_kg == 25))
            ).scalars().first()
    if size is None:
        size = models.PackageSize(ukuran_kg=25, aktif=True)
        db.add(size)
        await db.flush()
    brand = (await db.execute(select(models.Brand)
                              .where(models.Brand.nama == "Cap Padi Emas"))
             ).scalars().first()
    if brand is None:
        brand = models.Brand(nama="Cap Padi Emas", tipe="house", aktif=True)
        db.add(brand)
        await db.flush()
    db.add(models.PackagingPurchase(
        kode=kode, packaging_material_id=mat.id, package_size_id=size.id,
        brand_id=brand.id, jumlah_lembar=lembar,
        tanggal=date(2026, 10, 7), waktu=now_local(), input_by=pemakai_id))
    await db.commit()


async def test_selepan_ditolak_admin_berhasil_lihat_stok_karung(pg):
    from sqlalchemy import select

    from app.models import User
    from app.penggilingan.inventory import models

    async with pg() as db:
        uid = (await db.execute(select(User.id).limit(1))).scalars().first()
        if uid is None:
            u = User(nama="Awal", role="admin", status="aktif")
            db.add(u)
            await db.commit()
            await db.refresh(u)
            uid = u.id
        await _beli(db, models, pemakai_id=uid, lembar=500, kode="PKP-UJIH-01")

    c_admin = await _klien(pg, peran="admin")
    try:
        r = await c_admin.get("/stok-karung")
        assert r.status_code == 200
        assert "Karung Laminasi" in r.text
    finally:
        await c_admin.aclose()

    c_g1 = await _klien(pg, peran="operator", g1=True)
    try:
        r = await c_g1.get("/stok-karung")
        assert r.status_code == 403, "operator Gudang 1 bukan pemilik layar ini"
    finally:
        await c_g1.aclose()


async def test_operator_ditolak_admin_berhasil_pindah_kepemilikan_karung(pg):
    from app.penggilingan.inventory import models

    async with pg() as db:
        from sqlalchemy import select

        from app.models import Pelanggan, User
        uid = (await db.execute(select(User.id).limit(1))).scalars().first()
        if uid is None:
            u = User(nama="Awal", role="admin", status="aktif")
            db.add(u)
            await db.flush()
            uid = u.id
            await db.commit()
        await _beli(db, models, pemakai_id=uid, lembar=200, kode="PKP-UJIH-02")
        pel = pelanggan_kledo(nama_pelanggan="Toko Makmur")
        db.add(pel)
        await db.commit()
        await db.refresh(pel)
        pelanggan_id = pel.id

    c_op = await _klien(pg, peran="operator")
    try:
        r = await c_op.post("/api/actions/pindah-kepemilikan-karung",
                           json={"karung": f"laminasi|25|Cap Padi Emas",
                                 "pelanggan": str(pelanggan_id), "jumlah": 50})
        assert r.status_code == 403
    finally:
        await c_op.aclose()

    c_admin = await _klien(pg, peran="admin")
    try:
        # Picker karung dulu — nilainya WAJIB cocok dengan yang dikirim di
        # bawah. Picker tujuan (`pelanggan-kledo`) juga dicek: KONTAK, bukan
        # pesanan jasa — "Toko Makmur" harus muncul APA ADANYA.
        r = await c_admin.get("/api/actions/karung-pabrik-tersedia")
        assert r.status_code == 200
        pilihan = r.json()
        nilai = next(p["value"] for p in pilihan if p["value"].startswith("laminasi|25|"))
        assert nilai == "laminasi|25|Cap Padi Emas"

        r = await c_admin.get("/api/actions/pelanggan-kledo")
        assert r.status_code == 200
        assert any(p["value"] == str(pelanggan_id) and p["label"] == "Toko Makmur"
                   for p in r.json())

        r = await c_admin.post("/api/actions/pindah-kepemilikan-karung",
                              json={"karung": nilai, "pelanggan": str(pelanggan_id),
                                    "jumlah": 50})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
    finally:
        await c_admin.aclose()

    c_admin2 = await _klien(pg, peran="admin")
    try:
        r = await c_admin2.get("/stok-karung-jasa")
        assert r.status_code == 200
        assert "Toko Makmur" in r.text
        assert "Karung Laminasi" in r.text
    finally:
        await c_admin2.aclose()
