"""`masukkan_broken_ke_silo` — SATU aksi mengganti "Catat broken (curah)" +
"Pindah broken ke silo" (laporan pemilik 7 Oktober 2026: mengetik 5.000 kg
di langkah lama berakhir "tercatat melebihi hasil mesin 500 kg" tanpa
operator pernah salah ketik — sebabnya bentuk borangnya, bukan angkanya).

Sumbernya otomatis: curah dulu (FIFO), lalu BONGKAR KARUNG bila kurang —
dibulatkan ke atas ke karung penuh, sisanya tetap jadi curah di stok.
Karung kosongnya TIDAK dikembalikan ke Stok Karung (keputusan pemilik
7 Oktober 2026: "tidak dilacak balik").
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh(pg, pemakai):
    """Satu penyosohan SELESAI: 8.000 kg broken keluar mesin, Silo C & D
    (jenis_isi='broken') tersedia sebagai tujuan."""
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
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo_pk = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g2.id, Silo.jenis_isi == "pk"))).scalars().first()
        if silo_pk is None:
            silo_pk = Silo(nama_silo="Silo A", warehouse_id=g2.id, jenis_isi="pk")
            db.add(silo_pk)
            await db.flush()
        silo_broken = {}
        for huruf in ("C", "D"):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}", Silo.warehouse_id == g2.id
            ))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=g2.id, jenis_isi="broken")
                db.add(s)
                await db.flush()
            silo_broken[huruf] = s.id
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        u.role = "superadmin"

        p = PolishingProcess(kode_proses="POL-UJIB-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo_pk.id,
                                  berat_awal_kg=20_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=20_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="broken",
                                  berat_kg=8_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()
        return {"user": u.id, "kode_pol": p.kode_proses, "proc_id": p.id,
                "silo": silo_broken}


async def _curah(pg, sosoh, berat_kg: float) -> None:
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_broken

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_broken(db, user=u, kode_pol=sosoh["kode_pol"], berat_kg=berat_kg)


async def _kemas(pg, sosoh, *, jumlah_karung: int, ukuran: int = 50) -> None:
    """Satu-satunya kombinasi sah untuk broken selain polos/25kg —
    lihat `packaging.KEMASAN_VALID`."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode_pol"], kategori="broken",
                            material_kode="putih", ukuran=ukuran,
                            jumlah_karung=jumlah_karung)


async def test_curah_cukup_tanpa_bongkar_karung(pg, sosoh):
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    await _curah(pg, sosoh, 3_000)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=2_000)
    assert r.moved_kg == 2_000
    assert r.dibongkar_dari_karung_kg == 0

    async with pg() as db:
        assert await hitung_stok_broken_curah(db) == 1_000  # 3.000 - 2.000 terpakai di silo


async def test_curah_kurang_bongkar_karung_otomatis(pg, sosoh):
    """1.000 kg curah + minta masuk silo 3.500 kg -> kekurangan 2.500 kg,
    dibulatkan ke atas ke karung 50kg: 50 karung = 2.500 kg pas (uji kasus
    genap dulu, kasus sisa di uji berikutnya)."""
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    await _curah(pg, sosoh, 1_000)
    await _kemas(pg, sosoh, jumlah_karung=60)  # 3.000 kg berkarung (50kg/karung)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=3_500)
    assert r.moved_kg == 3_500
    assert r.dibongkar_dari_karung_kg == 2_500  # 50 karung x 50kg

    async with pg() as db:
        from app.models import FinishedGoodsStock, ProductSku
        from sqlalchemy import func, select
        sisa_karung = (await db.execute(
            select(func.coalesce(func.sum(FinishedGoodsStock.jumlah_karung), 0))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(ProductSku.kategori == "broken",
                   FinishedGoodsStock.source_id == sosoh["proc_id"])
        )).scalar_one()
        assert sisa_karung == 10  # 60 - 50 dibongkar
        # Curah stok: 1.000 (lama) + 2.500 (dibongkar) - 3.500 (masuk silo) = 0
        assert await hitung_stok_broken_curah(db) == 0


async def test_bongkar_karung_sisanya_jadi_curah(pg, sosoh):
    """Kekurangan tak genap kelipatan ukuran karung -> sisa karung yang
    dibongkar tapi tak terpakai jadi curah BARU di stok, bukan hilang."""
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    await _curah(pg, sosoh, 500)
    await _kemas(pg, sosoh, jumlah_karung=40)  # 2.000 kg berkarung (50kg/karung)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        # kekurangan = 1.290 - 500 = 790 -> ceil(790/50) = 16 karung = 800 kg
        # (bukan kelipatan genap 50 — sisanya 10 kg harus jadi curah baru).
        r = await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=1_290)
    assert r.moved_kg == 1_290
    assert r.dibongkar_dari_karung_kg == 800  # 16 karung x 50kg, dibulatkan ke atas dari 790

    async with pg() as db:
        # 500 (curah lama) + 800 (dibongkar) - 1.290 (masuk silo) = 10 kg sisa curah
        assert await hitung_stok_broken_curah(db) == 10


async def test_melebihi_curah_plus_karung_ditolak(pg, sosoh):
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_broken_ke_silo

    await _curah(pg, sosoh, 500)
    await _kemas(pg, sosoh, jumlah_karung=8)  # 400 kg berkarung (50kg/karung)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(Gudang2Error) as e:
            await masukkan_broken_ke_silo(
                db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=1_000)
    assert "tak bisa memasukkan" in str(e.value)


async def test_dua_pemilik_berbeda_silo_ditolak(pg, sosoh):
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_broken_ke_silo

    await _curah(pg, sosoh, 1_000)
    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-040", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.commit()
        jasa_id = jasa.id

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=500)

    # Silo C sudah milik pabrik — masukkan broken JASA ke sana ditolak.
    await _curah(pg, sosoh, 300)  # gabah pabrik lagi, abaikan — kita butuh curah utk jasa
    async with pg() as db:
        from app.models import ByproductStock
        from app.database import now_local
        u = await db.get(User, sosoh["user"])
        kini = now_local()
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=sosoh["proc_id"], berat_kg=200,
                              tanggal=kini.date(), waktu=kini, input_by=u.id,
                              jasa_id=jasa_id))
        await db.commit()

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(Gudang2Error):
            await masukkan_broken_ke_silo(
                db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=100,
                jasa_id=jasa_id)
