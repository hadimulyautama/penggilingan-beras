"""Tambah silo ke proses yang SEDANG BERJALAN — giling & penyosohan.

Laporan lapangan 7 Oktober 2026: *"proses yang berjalan baik itu proses
giling atau proses penyosohan, jika awalnya hanya menggunakan 1 silo, tidak
bisa menambahkan silo lainnya sebagai sumber bahan baku. pada prakteknya di
tengah-tengah proses, silo lainnya juga dipergunakan untuk mix bahan baku
jika dibutuhkan."* `start_milling`/`mulai_penyosohan` menerima BEBERAPA silo
— tetapi hanya pada SAAT MULAI; sesudah itu daftarnya terkunci. Fitur ini
membuka jalan mid-proses, menyalin penjaga yang sama (satu pemilik, silo tak
boleh dipakai proses lain) dari fungsi "mulai"-nya.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ═══════════════════════════ Giling (Gudang 1) ═══════════════════════════

@pytest_asyncio.fixture
async def g1(pg, pemakai, pemasok):
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse

    async with pg() as db:
        wh = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if wh is None:
            wh = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(wh)
            await db.flush()
        silo = {}
        for huruf in ("A", "B"):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}", Silo.warehouse_id == wh.id
            ))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=wh.id, status="kosong")
                db.add(s)
                await db.flush()
            silo[huruf] = s.id
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = wh.id
        u.role = "superadmin"
        await db.commit()
        return {"wh": wh.id, "silo": silo, "user": u.id, "pemasok": pemasok.id}


async def _isi_silo_g1(pg, g1, *, huruf: str, kode: str, kg: float,
                       jasa_id: int | None = None) -> None:
    from app.database import now_local
    from app.models import PurchaseBatch, SiloStorage, User

    async with pg() as db:
        u = await db.get(User, g1["user"])
        b = PurchaseBatch(
            kode_batch=kode, supplier_id=g1["pemasok"] if jasa_id is None else None,
            jasa_id=jasa_id, berat_total_kg=kg, kondisi_gabah="kering",
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, flag_unverified=False, sumber_berat="timbangan",
            status_batch="di_silo")
        db.add(b)
        await db.flush()
        db.add(SiloStorage(silo_id=g1["silo"][huruf], purchase_batch_id=b.id,
                           tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                           input_by=u.id, status="terisi", jasa_id=jasa_id))
        await db.commit()


async def test_picker_silo_g1_tambah_tak_menyembunyikan_bobot_belum_diketahui(pg, g1):
    """Laporan lapangan 9 Oktober 2026: "gabah yang baru datang tidak bisa
    ditambahkan ke giling yang berjalan" — picker `/actions/silo-g1-tambah`
    dulu menyaring `_silo_content_kg(...) <= 0`, dan gabah yang BARU dituang
    (belum sempat ditimbang kedua kalinya, `berat_total_kg IS NULL`) punya
    bobot DIKETAHUI = 0 meski silonya genuinely berisi — ia lenyap dari
    daftar "Silo yang ditambahkan", tampak seolah tak ada yang bisa
    ditambahkan. Pagarnya sekarang `_silo_active_rows` (baris ada/tidak),
    sama seperti `/actions/silo-siap-giling`.
    """
    from app.database import now_local
    from app.models import PurchaseBatch, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import start_milling
    from app.web.api import silo_g1_tambah

    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-TSP-01", kg=6_000)

    # Silo B: gabah SUDAH di silo, tapi truknya belum lewat timbangan kedua —
    # `berat_total_kg` masih NULL, persis keadaan "baru datang" di lapangan.
    async with pg() as db:
        u = await db.get(User, g1["user"])
        b = PurchaseBatch(
            kode_batch="GB-TSP-02", supplier_id=g1["pemasok"], berat_total_kg=None,
            kondisi_gabah="kering", tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, flag_unverified=True,
            sumber_berat="perkiraan", status_batch="di_silo")
        db.add(b)
        await db.flush()
        db.add(SiloStorage(silo_id=g1["silo"]["B"], purchase_batch_id=b.id,
                           tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                           input_by=u.id, status="terisi"))
        await db.commit()

    async with pg() as db:
        u = await db.get(User, g1["user"])
        r = await start_milling(db, user=u, nama_silo="A")

    async with pg() as db:
        u = await db.get(User, g1["user"])
        daftar = await silo_g1_tambah(induk=r.proc.kode_proses, user=u)
    assert "B" in [x["value"] for x in daftar], \
        f"Silo B (bobot belum diketahui) hilang dari picker: {daftar}"


async def test_tambah_silo_giling_menambah_bahan(pg, g1):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling, tambah_silo_giling

    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-TSG-01", kg=6_000)
    await _isi_silo_g1(pg, g1, huruf="B", kode="GB-TSG-02", kg=4_000)

    async with pg() as db:
        u = await db.get(User, g1["user"])
        r = await start_milling(db, user=u, nama_silo="A")
    assert r.berat_masuk == 6_000

    async with pg() as db:
        u = await db.get(User, g1["user"])
        r2 = await tambah_silo_giling(db, user=u, kode_proses=r.proc.kode_proses, nama_silo="B")
    assert r2.bertambah == 4_000
    async with pg() as db:
        from app.models import MillingProcess
        proc = await db.get(MillingProcess, r.proc.id)
        assert proc.berat_gabah_masuk_kg == 10_000


async def test_tambah_silo_giling_pemilik_beda_ditolak(pg, g1):
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang1.services.milling import MillingError, start_milling, tambah_silo_giling

    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-TSG-03", kg=5_000)
    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-030", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.commit()
        jasa_id = jasa.id
    await _isi_silo_g1(pg, g1, huruf="B", kode="GB-TSG-04", kg=3_000, jasa_id=jasa_id)

    async with pg() as db:
        u = await db.get(User, g1["user"])
        r = await start_milling(db, user=u, nama_silo="A")

    async with pg() as db:
        u = await db.get(User, g1["user"])
        with pytest.raises(MillingError):
            await tambah_silo_giling(db, user=u, kode_proses=r.proc.kode_proses, nama_silo="B")


async def test_tambah_silo_giling_yang_sedang_dipakai_proses_lain_ditolak(pg, g1):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import MillingError, start_milling, tambah_silo_giling

    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-TSG-05", kg=5_000)
    await _isi_silo_g1(pg, g1, huruf="B", kode="GB-TSG-06", kg=3_000)

    async with pg() as db:
        u = await db.get(User, g1["user"])
        r1 = await start_milling(db, user=u, nama_silo="A")
    async with pg() as db:
        u = await db.get(User, g1["user"])
        r2 = await start_milling(db, user=u, nama_silo="B")

    async with pg() as db:
        u = await db.get(User, g1["user"])
        with pytest.raises(MillingError) as e:
            await tambah_silo_giling(db, user=u, kode_proses=r1.proc.kode_proses, nama_silo="B")
    assert r2.proc.kode_proses in str(e.value)


async def test_tambah_silo_giling_proses_selesai_ditolak(pg, g1):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import (MillingError, finish_milling,
                                                            start_milling, tambah_silo_giling)

    await _isi_silo_g1(pg, g1, huruf="A", kode="GB-TSG-07", kg=5_000)
    await _isi_silo_g1(pg, g1, huruf="B", kode="GB-TSG-08", kg=3_000)
    async with pg() as db:
        u = await db.get(User, g1["user"])
        r = await start_milling(db, user=u, nama_silo="A")
    async with pg() as db:
        u = await db.get(User, g1["user"])
        await finish_milling(db, user=u, kode_proses=r.proc.kode_proses, berat_akhir=2_500)

    async with pg() as db:
        u = await db.get(User, g1["user"])
        with pytest.raises(MillingError) as e:
            await tambah_silo_giling(db, user=u, kode_proses=r.proc.kode_proses, nama_silo="B")
    assert "selesai" in str(e.value).lower()


# ═══════════════════════════ Penyosohan (Gudang 2) ═══════════════════════════

@pytest_asyncio.fixture
async def g2(pg, pemakai, pemasok):
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import PkGudang2Intake, PkPurchaseBatch

    async with pg() as db:
        wh = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if wh is None:
            wh = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(wh)
            await db.flush()
        silo = {}
        for huruf in ("A", "B"):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}", Silo.warehouse_id == wh.id
            ))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=wh.id, status="kosong")
                db.add(s)
                await db.flush()
            silo[huruf] = s.id
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = wh.id
        u.role = "superadmin"
        await db.commit()
        return {"wh": wh.id, "silo": silo, "user": u.id, "pemasok": pemasok.id}


async def _isi_silo_g2(pg, g2, *, huruf: str, kode: str, kg: float,
                       jasa_id: int | None = None) -> None:
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PkGudang2Intake, PkPurchaseBatch

    async with pg() as db:
        u = await db.get(User, g2["user"])
        b = PkPurchaseBatch(
            kode_batch=kode, supplier_id=g2["pemasok"] if jasa_id is None else None,
            jasa_id=jasa_id, berat_total_kg=kg,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="di_silo", flag_unverified=False,
            sumber_berat="timbangan")
        db.add(b)
        await db.flush()
        db.add(PkGudang2Intake(
            sumber_tipe="beli_luar", pk_purchase_batch_id=b.id,
            silo_id=g2["silo"][huruf], tujuan="silo",
            berat_kg=kg, bobot_final=True, tanggal_masuk=date.today(),
            waktu_masuk=now_local(), input_by=u.id, jasa_id=jasa_id))
        await db.commit()


async def test_tambah_silo_penyosohan_menambah_bahan(pg, g2):
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, tambah_silo_penyosohan

    await _isi_silo_g2(pg, g2, huruf="A", kode="PKB-TSS-01", kg=5_000)
    await _isi_silo_g2(pg, g2, huruf="B", kode="PKB-TSS-02", kg=3_000)

    async with pg() as db:
        u = await db.get(User, g2["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
    assert r.berat_awal_total == 5_000

    async with pg() as db:
        u = await db.get(User, g2["user"])
        r2 = await tambah_silo_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                          nama_silos=["B"])
    assert r2.berat_awal_total == 3_000

    async with pg() as db:
        from sqlalchemy import func, select

        from app.penggilingan.gudang2.models import PolishingSiloUsage
        total = (await db.execute(
            select(func.coalesce(func.sum(PolishingSiloUsage.berat_awal_kg), 0))
            .where(PolishingSiloUsage.polishing_process_id == r.proc.id)
        )).scalar_one()
        assert float(total) == 8_000


async def test_tambah_silo_penyosohan_pemilik_beda_ditolak(pg, g2):
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, tambah_silo_penyosohan
    from app.penggilingan.gudang2.service import Gudang2Error

    await _isi_silo_g2(pg, g2, huruf="A", kode="PKB-TSS-03", kg=4_000)
    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Pak Budi")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-031", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.commit()
        jasa_id = jasa.id
    await _isi_silo_g2(pg, g2, huruf="B", kode="PKB-TSS-04", kg=2_000, jasa_id=jasa_id)

    async with pg() as db:
        u = await db.get(User, g2["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])

    async with pg() as db:
        u = await db.get(User, g2["user"])
        with pytest.raises(Gudang2Error):
            await tambah_silo_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                         nama_silos=["B"])


async def test_tambah_silo_penyosohan_proses_selesai_ditolak(pg, g2):
    from app.models import User
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan,
                                                     tambah_silo_penyosohan)
    from app.penggilingan.gudang2.service import Gudang2Error

    await _isi_silo_g2(pg, g2, huruf="A", kode="PKB-TSS-05", kg=4_000)
    await _isi_silo_g2(pg, g2, huruf="B", kode="PKB-TSS-06", kg=2_000)
    async with pg() as db:
        u = await db.get(User, g2["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
    async with pg() as db:
        u = await db.get(User, g2["user"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="medium",
                           berat_kg=3_500)
    async with pg() as db:
        u = await db.get(User, g2["user"])
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses, nama_silo="A",
                                 sisa_kg=0)

    async with pg() as db:
        u = await db.get(User, g2["user"])
        with pytest.raises(Gudang2Error) as e:
            await tambah_silo_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                         nama_silos=["B"])
    assert "selesai" in str(e.value).lower()
