"""Bekatul otomatis; stok curah dan kemasan historis tetap saling mengurangi."""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh_bekatul(pg):
    """Satu penyosohan SELESAI dengan 1.000 kg bekatul tercatat keluar mesin."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (PackageSize, PackagingMaterial, Silo, Supplier, User,
                            Warehouse)
    from app.penggilingan.gudang2.models import (PkPurchaseBatch, PolishingOutputLog,
                                                 PolishingProcess, PolishingSiloUsage)
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
            await db.flush()
        silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
        u = User(nama="Op Polesan", role="operator", status="aktif",
                 default_warehouse_id=g2.id)
        s = Supplier(nama_supplier="UD Sumber")
        db.add_all([silo, u, s])
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-BK-01", supplier_id=s.id, berat_total_kg=10_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        p = PolishingProcess(kode_proses="POL-BK-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=10_000, berat_masuk_kg=0,
                                  berat_akhir_kg=0, berat_terpakai_kg=10_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="bekatul",
                                  berat_kg=1_000, waktu_update=now_local(),
                                  input_by=u.id))
        # Ukuran 40 kg & karung bekas wajib ada di master — keduanya disemai.
        assert (await db.execute(select(PackageSize).where(
            PackageSize.ukuran_kg == 40))).scalars().first(), \
            "ukuran 40 kg belum disemai"
        assert (await db.execute(select(PackagingMaterial).where(
            PackagingMaterial.kode == "bekas"))).scalars().first()
        await db.commit()
        return {"user": u.id, "kode": p.kode_proses, "proses_id": p.id}


async def _curah(pg, uid, kode, kg):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    async with pg() as db:
        return await catat_bekatul(db, user=await db.get(User, uid),
                                   kode_pol=kode, berat_kg=kg)


async def test_bekatul_dikemas_otomatis_tanpa_menulis_transaksi(pg,sosoh_bekatul):
    from app.services.stok import stok_produk
    from app.models import FinishedGoodsStock
    from sqlalchemy import select,func
    async with pg() as db:
        k=next(k for k in await stok_produk(db) if k.jenis=='bekatul')
        assert (k.sisa_kg,k.jumlah_karung_otomatis,k.curah_otomatis_kg)==(1000,25,0)
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==0


async def test_packing_manual_ditolak_meski_ada_sisa_setelah_curah(pg,sosoh_bekatul):
    from app.models import User
    from app.penggilingan.inventory import finished_goods as fg
    await _curah(pg,sosoh_bekatul['user'],sosoh_bekatul['kode'],800)
    async with pg() as db:
        with pytest.raises(fg.InventoryError,match='otomatis'):
            await fg.catat_packing(db,user=await db.get(User,sosoh_bekatul['user']),kode_pol=sosoh_bekatul['kode'],kategori='bekatul',material_kode='bekas',ukuran=40,jumlah_karung=5)


async def test_karung_dan_curah_historis_terbaca_tanpa_stok_ganda(pg,sosoh_bekatul):
    from app.models import User
    from app.services.stok import stok_produk
    from tests.pg.packing_historis import siapkan_packing_historis
    async with pg() as db:
        await siapkan_packing_historis(db,user=await db.get(User,sosoh_bekatul['user']),kode_pol=sosoh_bekatul['kode'],kategori='bekatul',material_kode='bekas',ukuran=40,jumlah_karung=20)
    await _curah(pg,sosoh_bekatul['user'],sosoh_bekatul['kode'],200)
    async with pg() as db:
        k=next(k for k in await stok_produk(db) if k.jenis=='bekatul')
        assert (k.sisa_kg,k.kemasan_stok_kg,k.curah_stok_kg)==(1000,800,200)
        assert (k.jumlah_karung_otomatis,k.curah_otomatis_kg)==(25,0)
        from app.penggilingan.inventory.finished_goods import catat_bekatul, InventoryError
        with pytest.raises(InventoryError):
            await catat_bekatul(db,user=await db.get(User,sosoh_bekatul['user']),kode_pol=sosoh_bekatul['kode'],berat_kg=1)


async def test_curah_historis_sebagian_tidak_menggandakan_saldo_otomatis(pg,sosoh_bekatul):
    from app.services.stok import stok_produk
    await _curah(pg,sosoh_bekatul['user'],sosoh_bekatul['kode'],800)
    async with pg() as db:
        k=next(k for k in await stok_produk(db) if k.jenis=='bekatul')
        assert (k.sisa_kg,k.curah_stok_kg,k.curah_kg)==(1000,800,200)
        assert (k.jumlah_karung_otomatis,k.curah_otomatis_kg)==(25,0)


async def test_penyosohan_tanpa_catatan_bekatul_tetap_bisa_mencatat_curah(pg, sosoh_bekatul):
    """Pabrik yang tak menimbang bekatulnya di mesin tidak boleh ikut terkunci.

    Pagar batas-atas hanya berlaku bila hasil bekatulnya MEMANG tercatat pada
    penyosohan itu. Tanpa catatan hasil, packing juga mustahil — jadi tak ada
    jalan kedua yang bisa menggandakan angkanya, dan menolak di sini cuma akan
    mematikan pencatatan yang sudah berjalan bertahun-tahun.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingProcess

    async with pg() as db:
        p = PolishingProcess(kode_proses="POL-BK-02", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=sosoh_bekatul["user"])
        db.add(p)
        await db.commit()
        kode = p.kode_proses
    # Tak ada satu pun `polishing_output_logs` bekatul untuk proses ini.
    assert await _curah(pg, sosoh_bekatul["user"], kode, 5_000) == 5_000
