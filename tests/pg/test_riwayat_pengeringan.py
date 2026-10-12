"""Layar Riwayat Pengeringan — sub-menu "Riwayat Proses" (7 Oktober 2026).

⚠⚠ TANPA SATU KOLOM PUN BERNAMA "SUSUT" — bukan kelalaian. Lihat catatan
panjang di `drying.riwayat_pengeringan()`: tak ada satu tempat pun di basis
data ini yang menyimpan berat gabah KERING keluar dryer, jadi susut
pengeringan secara jujur tak bisa dihitung. Berkas ini membuktikan kartunya
menyebut yang BENAR-BENAR tercatat (bahan basah, kadar air, status silo),
bukan menebak angka yang tak pernah ada.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.orm import selectinload

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang 1 dengan satu dryer aktif — lewat penyemai yang sama produksi."""
    from sqlalchemy import select

    from app.models import Dryer, User, Warehouse
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        d = (await db.execute(select(Dryer).where(
            Dryer.warehouse_id == g1.id))).scalars().first()
        if d is None:
            d = Dryer(nama="Dryer 1", warehouse_id=g1.id, kapasitas_kg=30_000,
                      status="aktif")
            db.add(d)
        d.kapasitas_kg = 30_000
        d.status = "aktif"
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        await db.commit()
        return {"user": u.id, "g1": g1.id, "pemasok": pemasok.id}


_N = [0]


async def _batch_basah(pg, pabrik: dict, kg: float) -> str:
    from app.database import now_local
    from app.models import PurchaseBatch, User

    _N[0] += 1
    kode = f"GB-RPK-{_N[0]:02d}"
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        db.add(PurchaseBatch(
            kode_batch=kode, supplier_id=pabrik["pemasok"], berat_total_kg=kg,
            kondisi_gabah="basah", tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, flag_unverified=False,
            sumber_berat="timbangan"))
        await db.commit()
    return kode


async def _lot_selesai(pg, pabrik: dict, *, masuk_kg: float = 8_000.0,
                       ka_akhir: float = 13.0) -> str:
    """Satu lot dari masuk dryer sampai pendinginan DITUTUP, jalur sungguhan.

    TIDAK dipindah ke silo — dryer-nya tetap "dipakai" lot ini sampai
    `_ke_silo` dipanggil terpisah. Pemanggil yang membuat lebih dari satu
    lot berurutan WAJIB memindah yang sebelumnya dulu (`_ke_silo`),
    persis seperti operator sungguhan: dryer tak bisa menerima batch baru
    selama lot sebelumnya belum dikosongkan ke silo.
    """
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr

    kode_batch = await _batch_basah(pg, pabrik, masuk_kg)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await dr.masuk_dryer(db, user=u, kode_batch_list=[kode_batch])
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        lot = (await dr.start_drying(db, user=u, target_kadar_air=13.0)).lot.kode_lot
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await dr.finish_drying(db, user=u, kode_lot=lot, kadar_air_akhir=ka_akhir)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await dr.finish_cooling(db, user=u, kode_lot=lot)
    return lot


async def _ke_silo(pg, pabrik: dict, kode_lot: str, *, huruf: str = "A") -> None:
    """Pindah lot ke silo Gudang 1 — mengosongkan dryer untuk lot berikutnya."""
    from app.models import User
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await masuk_silo(db, user=u, nama_silo=huruf, kode_lot=kode_lot,
                         kode_batch=None)


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
        a = ProduksiAkun(user_id=u.id, username=f"rp{u.id}",
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
    kode = await _lot_selesai(pg, pabrik)
    c = await _klien(pg, peran=peran, gudang=gudang, lihat=lihat)
    try:
        r = await c.get("/riwayat-pengeringan")
    finally:
        await c.aclose()
    assert r.status_code == 200, (peran, r.status_code)
    assert kode in r.text


async def test_export_laporan_pdf_per_lot(pg, pabrik):
    from pypdf import PdfReader
    from io import BytesIO
    from sqlalchemy import select
    from app.models import DryingLot, PurchaseBatch

    kode = await _lot_selesai(pg, pabrik)
    async with pg() as db:
        lot = (await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode))).scalar_one()
        # Batch yang baru dibuat adalah satu-satunya batch yang terkait lot ini.
        from app.models import DryingLotBatch
        batch_id = await db.scalar(select(DryingLotBatch.purchase_batch_id).where(
            DryingLotBatch.drying_lot_id == lot.id))
        batch = await db.get(PurchaseBatch, batch_id)
        batch.no_polisi_truk = "AB 1234 CD"
        lot_id = lot.id
        await db.commit()

    c = await _klien(pg, peran="superadmin")
    try:
        viewer = await c.get(f"/riwayat-pengeringan/{lot_id}/laporan")
        inline = await c.get(f"/riwayat-pengeringan/{lot_id}/laporan.pdf")
        response = await c.get(f"/riwayat-pengeringan/{lot_id}/laporan.pdf?unduh=1")
    finally:
        await c.aclose()

    assert viewer.status_code == 200
    assert "Kembali ke riwayat" in viewer.text
    assert "Bagikan PDF" in viewer.text
    assert inline.headers["content-disposition"].startswith("inline;")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    text = "\n".join(page.extract_text() or "" for page in PdfReader(
        BytesIO(response.content)).pages)
    assert kode in text
    assert "Pemasok Uji" in text
    assert "AB 1234 CD" in text
    assert "Waktu dan durasi proses" in text


async def test_operator_gudang_dua_ditolak_rutenya_bukan_cuma_pintunya(pg, pabrik):
    await _lot_selesai(pg, pabrik)
    c = await _klien(pg, peran="operator", gudang="Gudang 2", lihat="operator:g2")
    try:
        r = await c.get("/riwayat-pengeringan")
        beranda = await c.get("/")
    finally:
        await c.aclose()
    assert r.status_code == 403
    assert beranda.status_code == 200
    assert "/riwayat-pengeringan" not in beranda.text


# ═════════════════ 2 · APA YANG TERGAMBAR ═════════════════

async def test_kartu_menggambar_bahan_dan_ka_tanpa_susut(pg, pabrik):
    kode = await _lot_selesai(pg, pabrik, masuk_kg=8_000, ka_akhir=13.5)
    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-pengeringan")
    finally:
        await c.aclose()
    t = r.text
    assert kode in t
    assert "Pemasok Uji" in t
    assert "13.50%" in t  # kadar air terakhir — `_fmt_ka` memakai ":g", bukan koma
    assert "susut" not in t.lower(), "tak boleh ada klaim susut — datanya tak pernah ada"


async def test_lot_belum_dingin_tak_masuk_riwayat(pg, pabrik):
    """`status=='selesai'` cuma menutup fase KERING — riwayat menunggu
    pendinginannya TUNTAS juga."""
    from app.models import User
    from app.penggilingan.gudang1.services import drying as dr

    selesai = await _lot_selesai(pg, pabrik)
    await _ke_silo(pg, pabrik, selesai)
    kode_batch = await _batch_basah(pg, pabrik, 3_000)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await dr.masuk_dryer(db, user=u, kode_batch_list=[kode_batch])
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        belum_dingin = (await dr.start_drying(
            db, user=u, target_kadar_air=13.0)).lot.kode_lot
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        # Fase kering ditutup, tapi pendinginan BELUM — lewat `finish_drying`
        # saja, tanpa `finish_cooling`.
        await dr.finish_drying(db, user=u, kode_lot=belum_dingin,
                               kadar_air_akhir=13.0)
    from sqlalchemy import select
    from hmu_core.proses_db import ProsesTerpadu
    async with pg() as db:
        bersama = (await db.execute(select(ProsesTerpadu).options(
            selectinload(ProsesTerpadu.arus)).where(
            ProsesTerpadu.tabel_sumber == "drying_lots",
            ProsesTerpadu.kode == belum_dingin,
        ))).scalar_one()
        pendinginan = (await db.execute(select(ProsesTerpadu).options(
            selectinload(ProsesTerpadu.arus)).where(
            ProsesTerpadu.tabel_sumber == "drying_cooling",
            ProsesTerpadu.id_sumber == bersama.id_sumber,
        ))).scalar_one()
        assert bersama.status == "selesai"
        assert pendinginan.status == "berjalan"
        assert not [arus for arus in bersama.arus if arus.arah == "hasil"]

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-pengeringan")
    finally:
        await c.aclose()
    assert selesai in r.text
    assert belum_dingin not in r.text


async def test_status_silo_tersebut_setelah_dipindah(pg, pabrik):
    from app.models import User
    from app.penggilingan.gudang1.services.silo import masuk_silo

    kode = await _lot_selesai(pg, pabrik)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await masuk_silo(db, user=u, nama_silo="A", kode_lot=kode, kode_batch=None)

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-pengeringan")
    finally:
        await c.aclose()
    assert "Silo A" in r.text
    assert "Belum dipindah ke silo" not in r.text


async def test_belum_dipindah_ke_silo_disebut_jujur(pg, pabrik):
    await _lot_selesai(pg, pabrik)
    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-pengeringan")
    finally:
        await c.aclose()
    assert "Belum dipindah ke silo" in r.text


# ═════════════════ 3 · BORONGAN, BUKAN SATU PER KARTU ═════════════════

async def test_jumlah_kueri_tetap_walau_kartunya_bertambah(pg, pabrik, hitung_kueri):
    from app.penggilingan.gudang1.services.drying import riwayat_pengeringan

    kode = await _lot_selesai(pg, pabrik, masuk_kg=5_000)
    await _ke_silo(pg, pabrik, kode)
    async with pg() as db:
        async with hitung_kueri() as satu:
            await riwayat_pengeringan(db)

    for _ in range(5):
        kode = await _lot_selesai(pg, pabrik, masuk_kg=2_000)
        await _ke_silo(pg, pabrik, kode)
    async with pg() as db:
        async with hitung_kueri() as enam:
            kartu, _ = await riwayat_pengeringan(db)
    assert len(kartu) == 6
    assert enam.jumlah == satu.jumlah, (
        f"kuerinya tumbuh bersama jumlah kartu: {satu.jumlah} → {enam.jumlah}\n"
        + "\n".join(enam.perintah[:12]))


async def test_halaman_berikutnya_memakai_kursor_bukan_nomor(pg, pabrik):
    from app.penggilingan.gudang1.services.drying import riwayat_pengeringan

    for _ in range(3):
        kode = await _lot_selesai(pg, pabrik, masuk_kg=2_000)
        await _ke_silo(pg, pabrik, kode)
    async with pg() as db:
        hal1, lagi1 = await riwayat_pengeringan(db, batas=2)
        assert lagi1 and len(hal1) == 2
        hal2, lagi2 = await riwayat_pengeringan(db, batas=2, sebelum=hal1[-1].id)
    assert not lagi2 and len(hal2) == 1
    assert {k.id for k in hal1} & {k.id for k in hal2} == set()
