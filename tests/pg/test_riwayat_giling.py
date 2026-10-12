"""Layar Riwayat Penggilingan — sub-menu "Riwayat Proses" (7 Oktober 2026).

Padanan `/riwayat-sosoh` untuk Gudang 1: kartu TIAP giling SELESAI, terbaru
dulu — termasuk yang PK-nya sudah habis terkirim/terjual (beda dari `/stok`,
yang membuang lot habis karena ia hanya menjawab "apa yang MASIH ADA").
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang 1 bersilo A, KOSONG — `_giling_selesai` mengisinya sendiri
    tiap dipanggil (`_isi_silo`), sebab `start_milling` mengosongkannya
    tiap kali giling dimulai."""
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        s1 = (await db.execute(select(Silo).where(
            Silo.nama_silo == "Silo A", Silo.warehouse_id == g1.id))).scalars().first()
        if s1 is None:
            s1 = Silo(nama_silo="Silo A", warehouse_id=g1.id, status="kosong")
            db.add(s1)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        await db.commit()
        return {"user": u.id, "silo": s1.id, "pemasok": pemasok.id}


_N = [0]


async def _isi_silo(pg, pabrik: dict, kg: float) -> None:
    """Isi ULANG Silo A — `start_milling` mengosongkannya tiap kali dipanggil,
    jadi giling KEDUA dan seterusnya butuh batch baru sebelum bisa dimulai."""
    from app.database import now_local
    from app.models import PurchaseBatch, Silo, SiloStorage, User

    _N[0] += 1
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        silo = await db.get(Silo, pabrik["silo"])
        b = PurchaseBatch(kode_batch=f"GB-RGL-{_N[0]:02d}",
                          supplier_id=pabrik["pemasok"],
                          berat_total_kg=kg, kondisi_gabah="kering",
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


async def _giling_selesai(pg, pabrik: dict, *, masuk_kg: float = 10_000.0,
                          berat_akhir: float = 6_500.0) -> str:
    """Satu giling dari awal sampai DITUTUP, lewat jalur sungguhannya.

    Silo A diisi ulang DULU — fixture `pabrik` hanya mengisinya SEKALI, dan
    `start_milling` mengosongkannya tiap kali giling dimulai.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.milling import finish_milling, start_milling

    await _isi_silo(pg, pabrik, masuk_kg)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo="A")
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        s = await finish_milling(db, user=u, kode_proses=r.proc.kode_proses,
                                 berat_akhir=berat_akhir)
    return s.proc.kode_proses


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
        a = ProduksiAkun(user_id=u.id, username=f"rg{u.id}",
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
    kode = await _giling_selesai(pg, pabrik)
    c = await _klien(pg, peran=peran, gudang=gudang, lihat=lihat)
    try:
        r = await c.get("/riwayat-giling")
    finally:
        await c.aclose()
    assert r.status_code == 200, (peran, r.status_code)
    assert kode in r.text


async def test_operator_gudang_dua_ditolak_rutenya_bukan_cuma_pintunya(pg, pabrik):
    await _giling_selesai(pg, pabrik)
    c = await _klien(pg, peran="operator", gudang="Gudang 2", lihat="operator:g2")
    try:
        r = await c.get("/riwayat-giling")
        beranda = await c.get("/")
    finally:
        await c.aclose()
    assert r.status_code == 403
    assert beranda.status_code == 200
    assert "/riwayat-giling" not in beranda.text


# ═════════════════ 2 · APA YANG TERGAMBAR ═════════════════

async def test_kartu_menggambar_rendemen_dan_bahan(pg, pabrik):
    kode = await _giling_selesai(pg, pabrik, berat_akhir=6_500)
    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-giling")
    finally:
        await c.aclose()
    t = r.text
    assert kode in t
    assert "65,0%" in t  # 6.500 / 10.000
    assert "Pemasok Uji" in t  # batch asalnya tersebut


async def test_laporan_giling_pdf_bisa_dibuka_dan_diunduh(pg, pabrik):
    from sqlalchemy import select
    from app.models import MillingProcess, PurchaseBatch

    kode = await _giling_selesai(pg, pabrik, berat_akhir=6_500)
    async with pg() as db:
        process = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == kode))).scalar_one()
        batch = await db.get(PurchaseBatch, process.purchase_batch_id)
        batch.no_polisi_truk = "AB 1234 CD"
        await db.commit()
        process_id = process.id

    c = await _klien(pg, peran="superadmin")
    try:
        page = await c.get(f"/riwayat-giling/{process_id}/laporan")
        inline = await c.get(f"/riwayat-giling/{process_id}/laporan.pdf")
        download = await c.get(f"/riwayat-giling/{process_id}/laporan.pdf?unduh=1")
    finally:
        await c.aclose()

    assert page.status_code == 200
    assert "Kembali ke riwayat" in page.text
    assert "Bagikan PDF" in page.text
    assert inline.status_code == download.status_code == 200
    assert inline.headers["content-type"].startswith("application/pdf")
    assert inline.headers["content-disposition"].startswith("inline;")
    assert download.headers["content-disposition"].startswith("attachment;")
    from pypdf import PdfReader
    from io import BytesIO
    text = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(inline.content)).pages)
    assert kode in text
    assert "Pemasok Uji" in text
    assert "AB 1234 CD" in text
    assert "Waktu proses" in text


async def test_hanya_yang_selesai_yang_masuk_riwayat(pg, pabrik):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling

    selesai = await _giling_selesai(pg, pabrik)
    await _isi_silo(pg, pabrik, 3_000)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        jalan = (await start_milling(db, user=u, nama_silo="A")).proc.kode_proses

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-giling")
    finally:
        await c.aclose()
    assert selesai in r.text
    assert jalan not in r.text


async def test_giling_habis_terkirim_tetap_tercatat_di_riwayat(pg, pabrik):
    """⭐ Beda dari `/stok`: lot yang PK-nya sudah habis terkirim/terjual TAK
    HILANG dari riwayat — justru itu intinya."""
    from app.models import User
    from app.services.transfer import create_internal_transfer

    kode = await _giling_selesai(pg, pabrik, berat_akhir=5_000)
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        await create_internal_transfer(
            db, user=u, kode_proses=kode, lokasi_tujuan="ditumpuk", berat=5_000)

    from app.services.stok import pk_gudang1
    async with pg() as db:
        lot = await pk_gudang1(db)
    assert kode not in {l.kode for l in lot}, "sudah habis — wajar tak di Stok"

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/riwayat-giling")
    finally:
        await c.aclose()
    assert kode in r.text, "riwayat wajib tetap memuatnya walau sudah habis"


# ═════════════════ 3 · BORONGAN, BUKAN SATU PER KARTU ═════════════════

async def test_jumlah_kueri_tetap_walau_kartunya_bertambah(pg, pabrik, hitung_kueri):
    from app.penggilingan.gudang1.services.milling import riwayat_giling

    await _giling_selesai(pg, pabrik)
    async with pg() as db:
        async with hitung_kueri() as satu:
            await riwayat_giling(db)

    for _ in range(5):
        await _giling_selesai(pg, pabrik, berat_akhir=1_000)
    async with pg() as db:
        async with hitung_kueri() as enam:
            kartu, _ = await riwayat_giling(db)
    assert len(kartu) == 6
    assert enam.jumlah == satu.jumlah, (
        f"kuerinya tumbuh bersama jumlah kartu: {satu.jumlah} → {enam.jumlah}\n"
        + "\n".join(enam.perintah[:12]))


async def test_halaman_berikutnya_memakai_kursor_bukan_nomor(pg, pabrik):
    from app.penggilingan.gudang1.services.milling import riwayat_giling

    for _ in range(3):
        await _giling_selesai(pg, pabrik, berat_akhir=1_000)
    async with pg() as db:
        hal1, lagi1 = await riwayat_giling(db, batas=2)
        assert lagi1 and len(hal1) == 2
        hal2, lagi2 = await riwayat_giling(db, batas=2, sebelum=hal1[-1].id)
    assert not lagi2 and len(hal2) == 1
    assert {k.id for k in hal1} & {k.id for k in hal2} == set()
