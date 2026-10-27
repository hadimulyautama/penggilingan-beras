"""`masukkan_beras_ke_silo` — beras (grade) jadi bahan baku silo, DUA pintu
(keputusan pemilik 8 Oktober 2026):

  · Silo Beras (`jenis_isi='beras'`) — campuran berdiri sendiri, sebangun
    silo broken.
  · Silo A/B (`jenis_isi='pk'`, TAK berubah bentuknya) — jalan masuk
    KETIGA: beras jadi bahan sosoh ulang.

KEDUANYA menerima jenis yang SAMA (`stok.BERAS_JENIS`) — "beras putih" pada
kalimat pemilik dibaca APA ADANYA (beras yang sudah digiling), bukan
bucket teknis `jenis_produk()`'s "mutu belum ditetapkan" (bucket itu tak
pernah punya baris nyata — lihat docstring `masukkan_beras_ke_silo`).

Sumbernya curah (DIHITUNG, beras tak punya tabel curah) dulu, lalu BONGKAR
KARUNG bila kurang. Karung yang dibongkar TIDAK dikembalikan ke Stok Karung
— "karung bekasnya tidak dihitung, dianggap rusak" (sama dengan keputusan
broken 7 Oktober 2026).
"""
from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh(pg, pemakai):
    """Satu penyosohan SELESAI: 8.000 kg medium keluar mesin. Silo A
    (jenis_isi='pk') dan Silo C (jenis_isi='beras') tersedia sebagai tujuan."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
            await db.flush()
        silo_pk = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g2.id, Silo.jenis_isi == "pk"))).scalars().first()
        if silo_pk is None:
            silo_pk = Silo(nama_silo="Silo A", warehouse_id=g2.id, jenis_isi="pk")
            db.add(silo_pk)
            await db.flush()
        silo_beras = (await db.execute(select(Silo).where(
            Silo.nama_silo == "Silo C", Silo.warehouse_id == g2.id
        ))).scalars().first()
        if silo_beras is None:
            silo_beras = Silo(nama_silo="Silo C", warehouse_id=g2.id, jenis_isi="beras")
            db.add(silo_beras)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        u.role = "superadmin"

        p = PolishingProcess(kode_proses="POL-UJIR-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo_pk.id,
                                  berat_awal_kg=20_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=20_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=8_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()
        return {"user": u.id, "kode_pol": p.kode_proses, "proc_id": p.id,
                "silo_pk": silo_pk.id, "silo_beras": silo_beras.id}


async def _kemas_grade(pg, sosoh, *, grade: str, jumlah_karung: int, ukuran: int = 25) -> None:
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode_pol"], kategori="beras_putih",
                            grade=grade, material_kode="biasa", ukuran=ukuran,
                            jumlah_karung=jumlah_karung)


async def test_curah_cukup_ke_silo_beras_tanpa_bongkar(pg, sosoh):
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.services.stok import beras_curah

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="C", berat_kg=3_000)
    assert r.moved_kg == 3_000
    assert r.dibongkar_dari_karung_kg == 0

    async with pg() as db:
        kartu = await beras_curah(db)
    k = next(b for b in kartu if b.kode_proses == sosoh["kode_pol"] and b.jenis == "medium")
    # 8.000 hasil - 3.000 dipindah ke silo = 5.000 masih "belum dicatat".
    # Tanpa suku `_dipindah_silo_proc`, ini akan terbaca 8.000 (dua kali lipat
    # begitu Silo C disosoh ulang: sekali di sini, sekali lagi hasil barunya).
    assert k.sisa_kg == 5_000


async def test_curah_kurang_bongkar_karung_otomatis(pg, sosoh):
    """1.000 kg curah dipindah, lalu minta 5.000 kg lagi -> kekurangan,
    dibongkar dari kemasan yang sudah dikarungi (25kg/karung)."""
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.services.stok import beras_curah

    await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=200)  # 5.000 kg berkarung
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        # Curah tersedia = 8.000 - 5.000 (dikemas) = 3.000. Minta 5.000:
        # kekurangan 2.000 -> ceil(2.000/25) = 80 karung = 2.000 kg pas.
        r = await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="C", berat_kg=5_000)
    assert r.moved_kg == 5_000
    assert r.dibongkar_dari_karung_kg == 2_000

    async with pg() as db:
        from sqlalchemy import func, select

        from app.models import FinishedGoodsStock
        sisa_karung = (await db.execute(
            select(func.coalesce(func.sum(FinishedGoodsStock.jumlah_karung), 0))
            .where(FinishedGoodsStock.source_id == sosoh["proc_id"])
        )).scalar_one()
        assert sisa_karung == 120  # 200 - 80 dibongkar
        kartu = await beras_curah(db)
    # Tak ada kartu tersisa: 8.000 hasil = 3.000 (dikemas sisa 120krg*25) +
    # 5.000 (dipindah ke silo) persis — tak ada yang "belum dicatat".
    assert not any(b.kode_proses == sosoh["kode_pol"] and b.jenis == "medium" for b in kartu)


async def test_tolak_jenis_tak_dikenal(pg, sosoh):
    """Jenis beras hanya boleh grade (`stok.BERAS_JENIS`) — "beras putih"
    pada kalimat pemilik dibaca APA ADANYA (beras yang sudah digiling),
    bukan bucket teknis `jenis_produk()`'s "mutu belum ditetapkan": bucket
    itu tak pernah punya baris nyata (`catat_output` hanya menerima grade),
    jadi menjadikannya syarat di sini akan mengunci pintu Silo A/B
    selamanya. Lihat docstring `masukkan_beras_ke_silo`."""
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_beras_ke_silo

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(Gudang2Error) as e:
            await masukkan_beras_ke_silo(
                db, user=u, kode_pol=sosoh["kode_pol"], jenis="beras_putih",
                nama_silo="C", berat_kg=500)
    assert "grade" in str(e.value).lower()


async def test_beras_bisa_masuk_silo_berlabel_broken(pg, sosoh):
    """Label jenis warisan silo tidak membatasi isi campurannya."""
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.service import (_g2_warehouse_id,
                                                   hitung_stok_silo,
                                                   masukkan_beras_ke_silo)

    async with pg() as db:
        wid = await _g2_warehouse_id(db)
        db.add(Silo(nama_silo="Silo D", warehouse_id=wid, jenis_isi="broken"))
        await db.commit()

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="D", berat_kg=500)
        assert await hitung_stok_silo(db, (await db.execute(
            select(Silo.id).where(Silo.nama_silo == "Silo D")
        )).scalar_one()) == 500


async def test_grade_ke_silo_pk_sebagai_bahan_sosoh_ulang(pg, sosoh):
    """Silo A/B (PK, TAK berubah bentuknya) menerima jenis GRADE yang SAMA
    dengan Silo Beras — jalan masuk ketiga, "disosoh ulang"."""
    from app.models import User
    from app.penggilingan.gudang2.service import hitung_stok_silo, masukkan_beras_ke_silo
    from app.services.stok import beras_curah

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="A", berat_kg=2_000)
    assert r.moved_kg == 2_000
    assert r.dibongkar_dari_karung_kg == 0

    async with pg() as db:
        kartu = await beras_curah(db)
    k = next(b for b in kartu if b.kode_proses == sosoh["kode_pol"] and b.jenis == "medium")
    assert k.sisa_kg == 6_000  # 8.000 - 2.000 dipindah ke Silo A


async def test_melebihi_curah_plus_karung_ditolak(pg, sosoh):
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_beras_ke_silo

    await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=40)  # 1.000 kg berkarung
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        # Curah tersedia = 8.000 - 1.000 = 7.000; kemasan 1.000 -> total 8.000.
        with pytest.raises(Gudang2Error) as e:
            await masukkan_beras_ke_silo(
                db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
                nama_silo="A", berat_kg=9_000)
    assert "tak bisa memasukkan" in str(e.value)


async def test_hitung_stok_silo_beras(pg, sosoh):
    from app.models import User
    from app.penggilingan.gudang2.service import hitung_stok_silo, masukkan_beras_ke_silo

    async with pg() as db:
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == 0

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="C", berat_kg=2_000)

    async with pg() as db:
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == 2_000


async def test_pemilik_silo_g2_membaca_beras_ke_silo(pg, sosoh):
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.services.jasa import pemilik_silo_g2

    async with pg() as db:
        assert await pemilik_silo_g2(db, sosoh["silo_beras"]) == set()

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="C", berat_kg=1_000)

    async with pg() as db:
        assert await pemilik_silo_g2(db, sosoh["silo_beras"]) == {None}


async def test_dua_pemilik_berbeda_silo_ditolak(pg, sosoh):
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_beras_ke_silo

    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-041", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.commit()
        jasa_id = jasa.id

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        # Silo C jadi milik pabrik dulu.
        await masukkan_beras_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
            nama_silo="C", berat_kg=500)

    # Beras milik jasa (via kemasan yang sudah berpindah kepemilikan) tak
    # boleh dituang ke silo yang sudah milik pabrik.
    await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=40)  # 1.000 kg
    async with pg() as db:
        from sqlalchemy import select

        from app.models import FinishedGoodsStock
        row = (await db.execute(
            select(FinishedGoodsStock).where(
                FinishedGoodsStock.source_id == sosoh["proc_id"])
        )).scalars().first()
        row.jasa_id = jasa_id
        await db.commit()

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(Gudang2Error):
            await masukkan_beras_ke_silo(
                db, user=u, kode_pol=sosoh["kode_pol"], jenis="medium",
                nama_silo="C", berat_kg=100, jasa_id=jasa_id)


@pytest.mark.parametrize("kemasan", [False, True])
async def test_batalkan_beras_silo_mengembalikan_sumber(pg, sosoh, kemasan):
    from sqlalchemy import select
    from app.models import User, ActivityLog, BerasKeSilo
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo, hitung_stok_silo
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.services.undo import undo_last
    from app.services.stok import beras_curah

    if kemasan:
        await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=40)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_beras_ke_silo(db, user=u, kode_pol=sosoh["kode_pol"],
            jenis="medium", nama_silo="C", berat_kg=8000 if kemasan else 1000)
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == (8000 if kemasan else 1000)
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.table_name == "beras_ke_silo").order_by(ActivityLog.id.desc()))).scalars().first()
        assert log.gudang == "g2"
        await undo_last(db, actor=u, cakupan=None, log_id=log.id)
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == 0
        assert not (await db.execute(select(BerasKeSilo))).scalars().all()
        stok = (await db.execute(select(FinishedGoodsStock))).scalars().all()
        assert sum(x.jumlah_karung for x in stok) == (40 if kemasan else 0)
        kartu = await beras_curah(db)
        k = next(x for x in kartu if x.kode_proses == sosoh["kode_pol"] and x.jenis == "medium")
        assert k.sisa_kg == (7000 if kemasan else 8000)


async def test_undo_beras_ditolak_setelah_silo_dipakai(pg, sosoh):
    from sqlalchemy import select
    from app.models import User, ActivityLog
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.services.undo import _undo_beras_masuk_silo, UndoError

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_beras_ke_silo(db, user=u, jenis="medium", sumber_stok="curah",
                                    nama_silo="C", berat_kg=1000)
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.table_name == "beras_ke_silo"))).scalars().one()
        await mulai_penyosohan(db, user=u, nama_silos=["C"])
        with pytest.raises(UndoError, match="sudah dipakai"):
            await _undo_beras_masuk_silo(db, log)


async def test_undo_input_beras_fifo_membatalkan_semua_sumber_sekaligus(pg, sosoh):
    from sqlalchemy import select
    from app.database import now_local
    from app.models import User, PolishingProcess, PolishingOutputLog, ActivityLog, BerasKeSilo
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo, hitung_stok_silo
    from app.services.undo import undo_last, UndoError

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        p = PolishingProcess(kode_proses="POL-FIFO-2", status="selesai",
            waktu_mulai=now_local(), waktu_selesai=now_local(), created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=1000, waktu_update=now_local(), input_by=u.id))
        await db.commit()
        await masukkan_beras_ke_silo(db, user=u, jenis="medium", sumber_stok="curah",
                                    nama_silo="C", berat_kg=9000)
        assert len((await db.execute(select(BerasKeSilo))).scalars().all()) == 2
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.table_name == "beras_ke_silo"))).scalars().one()
        await undo_last(db, actor=u, cakupan=None, log_id=log.id)
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == 0
        with pytest.raises(UndoError, match="sudah dibatalkan"):
            await undo_last(db, actor=u, cakupan=None, log_id=log.id)


async def test_undo_beras_kemasan_parsial_mempertahankan_asal_dan_pemilik(pg, sosoh):
    from sqlalchemy import select
    from app.models import User, ActivityLog
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo, hitung_stok_silo
    from app.services.undo import undo_last

    await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=40)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        stok = (await db.execute(select(FinishedGoodsStock))).scalars().one()
        asal = (stok.id, stok.source_type, stok.source_id, stok.product_sku_id,
                stok.jasa_id, stok.rice_quality_standard_id, stok.kemasan_mengurangi_stok)
        await masukkan_beras_ke_silo(db, user=u, jenis="medium",
            sumber_stok=f"sku:{stok.product_sku_id}", nama_silo="C", berat_kg=300)
        assert stok.jumlah_karung == 28
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.table_name == "beras_ke_silo"))).scalars().one()
        await undo_last(db, actor=u, cakupan=None, log_id=log.id)
        await db.refresh(stok)
        assert stok.jumlah_karung == 40
        assert stok.berat_total_kg == 1000
        assert asal == (stok.id, stok.source_type, stok.source_id, stok.product_sku_id,
                       stok.jasa_id, stok.rice_quality_standard_id, stok.kemasan_mengurangi_stok)
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == 0
        assert not (await db.execute(select(ActivityLog.id).where(
            ActivityLog.aksi == "beras_bongkar_karung",
            ActivityLog.dibatalkan_pada.is_(None)))).first()


async def test_undo_stok_habis_id_dipakai_ulang_dan_berat_aktual(pg, sosoh):
    from sqlalchemy import select
    from app.models import User, ActivityLog
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo
    from app.services.undo import undo_last
    from app.database import now_local

    await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=6, ukuran=50)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        stok = (await db.execute(select(FinishedGoodsStock))).scalars().one()
        stok.berat_total_kg = 275  # 6 karung nominal 50 kg, bobot tiket aktual 275.
        rid, sku = stok.id, stok.product_sku_id
        await db.commit()
        await masukkan_beras_ke_silo(db, user=u, jenis="medium",
            sumber_stok=f"sku:{sku}", nama_silo="C", berat_kg=275)
        lain = FinishedGoodsStock(id=rid, product_sku_id=sku,
            source_type="timbangan", source_id=999, jumlah_karung=10,
            berat_total_kg=500, waktu=now_local(), input_by=u.id)
        db.add(lain)
        await db.commit()
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.table_name == "beras_ke_silo"))).scalars().one()
        await undo_last(db, actor=u, cakupan=None, log_id=log.id)
        await db.refresh(lain)
        assert lain.berat_total_kg == 500 and lain.jumlah_karung == 10
        pulih = (await db.execute(select(FinishedGoodsStock).where(
            FinishedGoodsStock.source_type == "polishing",
            FinishedGoodsStock.source_id == sosoh["proc_id"]))).scalars().one()
        assert pulih.id != rid
        assert pulih.berat_total_kg == 275 and pulih.jumlah_karung == 6


@pytest.mark.parametrize("bertahap", [True, False])
async def test_karung_terakhir_retur_25kg_bisa_masuk_silo_dan_dibatalkan(pg, sosoh, bertahap):
    from sqlalchemy import select, func
    from app.database import now_local
    from app.models import User, ActivityLog, BerasKeSilo
    from app.penggilingan.inventory.models import (
        FinishedGoodsStock, CustomerReturn, CustomerReturnItem)
    from app.penggilingan.gudang2.service import masukkan_beras_ke_silo, hitung_stok_silo
    from app.services.undo import undo_last

    await _kemas_grade(pg, sosoh, grade="medium", jumlah_karung=11, ukuran=25)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        stok = (await db.execute(select(FinishedGoodsStock))).scalars().one()
        retur = CustomerReturn(kode="RET-UJI-TERAKHIR", timbangan_transaksi_id=12345,
            kode_tiket="TKT-UJI-RETUR", berat_tiket_kg=275, berat_rincian_kg=275,
            selisih_kg=0, input_by=u.id, waktu=now_local())
        db.add(retur)
        await db.flush()
        stok.source_type, stok.source_id = "retur", retur.id
        rinci = CustomerReturnItem(customer_return_id=retur.id,
            product_sku_id=stok.product_sku_id,
            rice_quality_standard_id=stok.rice_quality_standard_id,
            jumlah_karung=11, berat_total_kg=275, finished_goods_stock_id=stok.id)
        db.add(rinci)
        await db.commit()
        rid = stok.id
        for kg in ([200, 25, 25, 25] if bertahap else [275]):
            await masukkan_beras_ke_silo(db, user=u, jenis="medium",
                sumber_stok=f"sku:{stok.product_sku_id}", nama_silo="C", berat_kg=kg)
        await db.refresh(stok)
        await db.refresh(rinci)
        assert stok.jumlah_karung == 0 and stok.berat_total_kg == 0
        assert rinci.finished_goods_stock_id == rid
        assert rinci.jumlah_karung == 11 and rinci.berat_total_kg == 275
        assert await hitung_stok_silo(db, sosoh["silo_beras"]) == 275
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg))) == 275
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.table_name == "beras_ke_silo").order_by(ActivityLog.id.desc()))).scalars().first()
        await undo_last(db, actor=u, cakupan=None, log_id=log.id)
        await db.refresh(stok)
        assert stok.id == rid
        assert stok.jumlah_karung == (1 if bertahap else 11)
        assert stok.berat_total_kg == (25 if bertahap else 275)
