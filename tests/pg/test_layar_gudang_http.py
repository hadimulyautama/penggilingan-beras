"""`/gudang/{gid}` benar-benar dirender, dan gerbangnya benar-benar menutup.

Uji berkas `tests/test_layar_gudang.py` membaca sumbernya; yang di sini
MEMBUKA halamannya lewat HTTP. Keduanya perlu: yang pertama menangkap gerbang
yang salah dipilih, yang kedua menangkap halaman yang gerbangnya benar tetapi
templatnya gagal dirender — dan templat yang gagal hanya terlihat saat dibuka.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio


async def _klien(pg, *, role: str, gudang_nama: str | None = None) -> httpx.AsyncClient:
    """Satu orang yang sudah masuk. `gudang_nama` menetapkan gudang utamanya —
    itulah yang menentukan view operator (selepan vs polesan)."""
    from app.main import app
    from app.models import ProduksiAkun, User, Warehouse
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan
    from sqlalchemy import select

    async with pg() as db:
        wid = None
        if gudang_nama:
            w = (await db.execute(
                select(Warehouse).where(Warehouse.nama_gudang == gudang_nama))).scalars().first()
            if w is None:
                w = Warehouse(nama_gudang=gudang_nama, kode_fungsi={"Gudang 1 - Selepan": "g1", "Gudang 2 - Penyosohan": "g2"}[gudang_nama])
                db.add(w)
                await db.flush()
            wid = w.id
        u = User(nama=f"Uji {role}", role=role, status="aktif", default_warehouse_id=wid)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"uji{u.id}",
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan(role))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


@pytest.fixture
async def dua_gudang(pg):
    """Kedua gudang ada, masing-masing dengan satu silo — `_petak_g2` membacanya."""
    from app.models import Silo, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        await db.commit()
        return {"g1": g1.id, "g2": g2.id}


async def test_super_membuka_kedua_gudang(pg, dua_gudang):
    c = await _klien(pg, role="superadmin")
    async with c:
        for gid, nama, fungsi in (("g1", "Gudang 1", "Selepan"),
                                  ("g2", "Gudang 2", "Penyosohan")):
            r = await c.get(f"/gudang/{gid}")
            assert r.status_code == 200, r.text[:400]
            assert f"{nama} — {fungsi}" in r.text
            # Tombol kembali, bukan laci: halaman ini punya induk.
            assert 'class="bar__balik"' in r.text
            assert 'id="buka-laci"' not in r.text
            # Petak digambar (angkanya boleh nol; yang dijaga ADA selnya).
            assert "petak__sel" in r.text


async def test_operator_polesan_ditolak_di_gudang_sebelah(pg, dua_gudang):
    """Kesalahan yang tak kelihatan: halaman yang terbuka untuk orang yang
    salah. Operator polesan boleh melihat Gudang 2 dan TIDAK Gudang 1."""
    c = await _klien(pg, role="operator", gudang_nama="Gudang 2 - Penyosohan")
    async with c:
        assert (await c.get("/gudang/g2")).status_code == 200
        r = await c.get("/gudang/g1")
        assert r.status_code == 403, r.status_code
        assert "bukan gudang Anda" in r.text


async def test_operator_selepan_ditolak_di_gudang_sebelah(pg, dua_gudang):
    c = await _klien(pg, role="operator", gudang_nama="Gudang 1 - Selepan")
    async with c:
        assert (await c.get("/gudang/g1")).status_code == 200
        assert (await c.get("/gudang/g2")).status_code == 403


async def test_gudang_karangan_404_bukan_500(pg, dua_gudang):
    """Alamat diketik orang. Gudang yang tak dikenal harus dijawab 404 sebelum
    menyentuh basis data — bukan pecah di kueri dengan galat yang terbaca
    seperti kerusakan."""
    c = await _klien(pg, role="superadmin")
    async with c:
        assert (await c.get("/gudang/g9")).status_code == 404


async def test_tanpa_sesi_dilempar_ke_masuk(pg, dua_gudang):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://uji") as c:
        r = await c.get("/gudang/g1")
        assert r.status_code in (303, 401), r.status_code
