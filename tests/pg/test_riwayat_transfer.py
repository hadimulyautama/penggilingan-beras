"""Layar Riwayat Transfer — sub-menu "Riwayat Proses" (7 Oktober 2026).

⚠⚠ `InternalTransfer` BUKAN cermin: transfer yang DIBATALKAN tetap tampil di
riwayat, bertanda jelas — bukan hilang dari daftar. Berkas ini membuktikan
itu secara langsung, bukan cuma lewat `hitung_stok_broken_curah`-style
fungsi lain yang sudah benar duluan.
"""
from __future__ import annotations
from tests.pg.skenario_silo import pastikan_silo_kosong

from datetime import date

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang 1 bersilo A (kosong, diisi per panggilan) + Gudang 2 bersilo A."""
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
            db.add(g1)
            await db.flush()
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
            await db.flush()
        s1 = (await db.execute(select(Silo).where(
            Silo.nama_silo == "Silo A", Silo.warehouse_id == g1.id))).scalars().first()
        if s1 is None:
            s1 = Silo(nama_silo="Silo A", warehouse_id=g1.id, status="kosong")
            db.add(s1)
            await db.flush()
        s2 = (await db.execute(select(Silo).where(
            Silo.nama_silo == "Silo A", Silo.warehouse_id == g2.id))).scalars().first()
        if s2 is None:
            s2 = Silo(nama_silo="Silo A", warehouse_id=g2.id, status="kosong")
            db.add(s2)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        await db.commit()
        return {"user": u.id, "silo_g1": s1.id, "silo_g2": s2.id,
                "pemasok": pemasok.id}


_N = [0]


async def _pk_siap_kirim(pg, pabrik: dict, *, berat: float = 2_000.0) -> str:
    """Satu giling SELESAI dengan PK siap kirim — kode prosesnya."""
    from app.database import now_local
    from app.models import PurchaseBatch, Silo, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import finish_milling, start_milling

    _N[0] += 1
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        silo = await db.get(Silo, pabrik["silo_g1"])
        b = PurchaseBatch(kode_batch=f"GB-RTR-{_N[0]:02d}",
                          supplier_id=pabrik["pemasok"],
                          berat_total_kg=berat + 1_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u.id, flag_unverified=False,
                          sumber_berat="timbangan", status_batch="di_silo")
        db.add(b)
        await db.flush()
        db.add(SiloStorage(silo_id=silo.id, purchase_batch_id=b.id,
                           tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                           input_by=u.id, status="terisi"))
        silo.status = "terisi"
        await db.commit()
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo="A")
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
        s = await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=berat)
    return s.proc.kode_proses


async def _transfer(pg, pabrik: dict, kode_proses: str, *, berat: float,
                    lokasi: str = "A") -> int:
    from app.models import User
    from app.services.transfer import create_internal_transfer

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await create_internal_transfer(
            db, user=u, kode_proses=kode_proses,
            lokasi_tujuan=lokasi, berat=berat)
    return r.transfer.id


async def _klien(pg, *, peran: str, gudang: str | None = None,
                 lihat: str | None = None) -> httpx.AsyncClient:
    from sqlalchemy import select

    from app.main import app
    from app.models import ProduksiAkun, User, Warehouse
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        wid = None
        if gudang:
            w = (await db.execute(select(Warehouse).where(
                Warehouse.nama_gudang.like(gudang + "%")))).scalars().first()
            wid = w.id if w else None
        u = User(nama=f"Uji {peran}", role=peran, status="aktif",
                 default_warehouse_id=wid)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"rt{u.id}",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan(peran))
        db.add(a)
        await db.commit()
        tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    if lihat:
        c.headers["X-Meja-Lihat"] = lihat
    return c


# ═════════════════ 1 · SIAPA YANG BOLEH MELIHAT ═════════════════

@pytest.mark.parametrize("peran,gudang,lihat", [
    ("superadmin", None, None),
    ("admin", None, None),
    ("operator", "Gudang 1", "operator:g1"),
])
async def test_tiga_yang_boleh(pg, pabrik, peran, gudang, lihat):
    kode = await _pk_siap_kirim(pg, pabrik)
    await _transfer(pg, pabrik, kode, berat=1_000)
    c = await _klien(pg, peran=peran, gudang=gudang, lihat=lihat)
    try:
        r = await c.get("/riwayat-transfer")
    finally:
        await c.aclose()
    assert r.status_code == 200, (peran, r.status_code)
    assert kode in r.text


async def test_operator_gudang_dua_ditolak_rutenya_bukan_cuma_pintunya(pg, pabrik):
    kode = await _pk_siap_kirim(pg, pabrik)
    await _transfer(pg, pabrik, kode, berat=1_000)
    c = await _klien(pg, peran="operator", gudang="Gudang 2", lihat="operator:g2")
    try:
        r = await c.get("/riwayat-transfer")
        beranda = await c.get("/")
    finally:
        await c.aclose()
    assert r.status_code == 403
    assert beranda.status_code == 200
    assert "/riwayat-transfer" not in beranda.text


# ═════════════════ 2 · APA YANG TERGAMBAR ═════════════════

async def test_tujuan_silo_dan_ditumpuk_tersebut(pg, pabrik):
    k1 = await _pk_siap_kirim(pg, pabrik, berat=1_000)
    await _transfer(pg, pabrik, k1, berat=1_000, lokasi="A")
    k2 = await _pk_siap_kirim(pg, pabrik, berat=800)
    await _transfer(pg, pabrik, k2, berat=800, lokasi="ditumpuk")

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-transfer")
    finally:
        await c.aclose()
    t = r.text
    assert k1 in t and k2 in t
    assert "Silo A" in t
    assert "Ditumpuk" in t


async def test_transfer_dibatalkan_tetap_tampil_bertanda(pg, pabrik):
    """⭐ Tidak disembunyikan — prinsip yang sama dipakai seluruh riwayat
    lain di app ini."""
    from app.services.undo import _undo_transfer

    kode = await _pk_siap_kirim(pg, pabrik, berat=1_500)
    tid = await _transfer(pg, pabrik, kode, berat=1_500)
    async with pg() as db:
        await _undo_transfer(db, tid)
        await db.commit()

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-transfer")
    finally:
        await c.aclose()
    t = r.text
    assert kode in t
    assert "Dibatalkan" in t


# ═════════════════ 3 · BORONGAN, BUKAN SATU PER KARTU ═════════════════

async def test_jumlah_kueri_tetap_walau_kartunya_bertambah(pg, pabrik, hitung_kueri):
    from app.services.transfer import riwayat_transfer

    k = await _pk_siap_kirim(pg, pabrik, berat=1_000)
    await _transfer(pg, pabrik, k, berat=1_000)
    async with pg() as db:
        async with hitung_kueri() as satu:
            await riwayat_transfer(db)

    for _ in range(5):
        k = await _pk_siap_kirim(pg, pabrik, berat=500)
        await _transfer(pg, pabrik, k, berat=500)
    async with pg() as db:
        async with hitung_kueri() as enam:
            kartu, _ = await riwayat_transfer(db)
    assert len(kartu) == 6
    assert enam.jumlah == satu.jumlah, (
        f"kuerinya tumbuh bersama jumlah kartu: {satu.jumlah} → {enam.jumlah}\n"
        + "\n".join(enam.perintah[:12]))


async def test_halaman_berikutnya_memakai_kursor_bukan_nomor(pg, pabrik):
    from app.services.transfer import riwayat_transfer

    for _ in range(3):
        k = await _pk_siap_kirim(pg, pabrik, berat=500)
        await _transfer(pg, pabrik, k, berat=500)
    async with pg() as db:
        hal1, lagi1 = await riwayat_transfer(db, batas=2)
        assert lagi1 and len(hal1) == 2
        hal2, lagi2 = await riwayat_transfer(db, batas=2, sebelum=hal1[-1].id)
    assert not lagi2 and len(hal2) == 1
    assert {k.id for k in hal1} & {k.id for k in hal2} == set()
