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
    """Sejak hasil mesin yang belum tercatat ikut dibukukan otomatis
    (Langkah 1.5), karung baru tersentuh sesudah pool ITU habis — dan
    mengemas 60 karung (3.000 kg) lebih dulu TURUT mengurangi pool "belum
    tercatat" (`_broken_dibukukan` menjumlah curah MAUPUN kemasan): dari
    8.000 kg hasil mesin, 3.000 kg sudah "dibukukan" lewat kemasan, sisa
    5.000 kg masih bisa dibukukan otomatis sebagai curah.

    Minta masuk silo 7.500 kg -> 5.000 kg dibukukan otomatis dari hasil
    mesin, kekurangan 2.500 kg, dibulatkan ke atas ke karung 50kg: 50 karung
    = 2.500 kg pas (uji kasus genap dulu, kasus sisa di uji berikutnya)."""
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    await _kemas(pg, sosoh, jumlah_karung=60)  # 3.000 kg berkarung (50kg/karung)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=7_500)
    assert r.moved_kg == 7_500
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
        # Curah stok: 5.000 (dibukukan otomatis) + 2.500 (dibongkar) - 7.500 (masuk silo) = 0
        assert await hitung_stok_broken_curah(db) == 0


async def test_bongkar_karung_sisanya_jadi_curah(pg, sosoh):
    """Kekurangan tak genap kelipatan ukuran karung, SESUDAH pool "belum
    tercatat" (8.000 kg hasil mesin − 2.000 kg yang sudah dikemas = 6.000 kg)
    dibukukan otomatis duluan -> sisa karung yang dibongkar tapi tak terpakai
    jadi curah BARU di stok, bukan hilang."""
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    await _kemas(pg, sosoh, jumlah_karung=40)  # 2.000 kg berkarung (50kg/karung)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        # 6.000 kg hasil mesin (belum tercatat) dibukukan otomatis duluan;
        # kekurangan sesudahnya = 6.790 - 6.000 = 790 -> ceil(790/50) = 16
        # karung = 800 kg (bukan kelipatan genap 50 — sisanya 10 kg harus
        # jadi curah baru).
        r = await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=6_790)
    assert r.moved_kg == 6_790
    assert r.dibongkar_dari_karung_kg == 800  # 16 karung x 50kg, dibulatkan ke atas dari 790

    async with pg() as db:
        # 6.000 (dibukukan otomatis) + 800 (dibongkar) - 6.790 (masuk silo) = 10 kg sisa curah
        assert await hitung_stok_broken_curah(db) == 10


async def test_melebihi_curah_plus_karung_ditolak(pg, sosoh):
    """400 kg sudah dikemas, 7.600 kg bisa dibukukan otomatis dari hasil
    mesin yang belum tercatat — 8.000 kg total tersedia (persis seluruh
    hasil mesinnya). Meminta lebih dari itu tetap ditolak."""
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_broken_ke_silo

    await _kemas(pg, sosoh, jumlah_karung=8)  # 400 kg berkarung (50kg/karung)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(Gudang2Error) as e:
            await masukkan_broken_ke_silo(
                db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=8_500)
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


async def test_picker_broken_proses_tersedia_curah_per_proses_bukan_global(pg, pemakai):
    """Laporan lapangan 10 Oktober 2026: dua proses PABRIK (POL-A sudah
    SEMUA curahnya dipindah ke silo, POL-B masih bersisa 50 kg) tampil di
    picker dengan angka curah yang SAMA PERSIS — keduanya membaca
    `hitung_stok_broken_curah()`, yang GLOBAL atas seluruh pemilik, bukan
    per `source_id`. POL-A (curahnya sendiri 0) tetap tampil seolah
    berbobot, lalu ditolak saat disubmit — `masukkan_broken_ke_silo`
    sendiri SUDAH benar menyaring per-proses.

    Dibuktikan di sini: picker sekarang menjawab curah MASING-MASING
    proses sendiri, bukan total gabungan.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.services.seed import seed_master
    from app.web.api import broken_proses_tersedia

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo_pk = Silo(nama_silo="Silo A", warehouse_id=g2.id, jenis_isi="pk")
        silo_c = Silo(nama_silo="Silo C", warehouse_id=g2.id, jenis_isi="broken")
        db.add_all([silo_pk, silo_c])
        await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        u.role = "superadmin"

        proc_a = PolishingProcess(kode_proses="POL-UJIG-A", status="proses",
                                  waktu_mulai=now_local(), created_by=u.id)
        proc_b = PolishingProcess(kode_proses="POL-UJIG-B", status="proses",
                                  waktu_mulai=now_local(), created_by=u.id)
        db.add_all([proc_a, proc_b])
        await db.flush()
        for p in (proc_a, proc_b):
            db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo_pk.id,
                                      berat_awal_kg=5_000, berat_akhir_kg=0,
                                      berat_terpakai_kg=5_000))
            db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="broken",
                                      berat_kg=1_000, waktu_update=now_local(),
                                      input_by=u.id))
        await db.commit()
        kode_a, kode_b, uid, silo_c_id = proc_a.kode_proses, proc_b.kode_proses, u.id, silo_c.id

    # Dua proses sumber tetap menyisakan stok, tetapi picker harus menjadikannya
    # satu tumpukan per pemilik.
    async with pg() as db:
        from app.penggilingan.inventory.finished_goods import catat_broken
        u = await db.get(User, uid)
        await catat_broken(db, user=u, kode_pol=kode_a, berat_kg=1_000)
    async with pg() as db:
        u = await db.get(User, uid)
        await masukkan_broken_ke_silo(
            db, user=u, kode_pol=kode_a, nama_silo="C", berat_kg=950)

    # POL-B juga menyisakan 50 kg.
    async with pg() as db:
        from app.penggilingan.inventory.finished_goods import catat_broken
        u = await db.get(User, uid)
        await catat_broken(db, user=u, kode_pol=kode_b, berat_kg=1_000)
    async with pg() as db:
        u = await db.get(User, uid)
        await masukkan_broken_ke_silo(
            db, user=u, kode_pol=kode_b, nama_silo="C", berat_kg=950)

    async with pg() as db:
        u = await db.get(User, uid)
        daftar = await broken_proses_tersedia(user=u)
    assert len(daftar) == 1 and daftar[0]["value"] == "pemilik|pabrik", daftar
    assert "100 kg" in daftar[0]["label"]
    async with pg() as db:
        u = await db.get(User, uid)
        from app.penggilingan.gudang2.service import masukkan_stok_broken_pemilik_ke_silo
        await masukkan_stok_broken_pemilik_ke_silo(
            db, user=u, jasa_id=None, nama_silo="C", berat_kg=75)
        from app.models import BrokenKeSilo, ByproductStock
        from app.penggilingan.gudang2.models import PolishingProcess
        from sqlalchemy import func, select
        sumber_berat = (await db.execute(
            select(ByproductStock.source_id, func.sum(BrokenKeSilo.berat_kg))
            .join(ByproductStock, ByproductStock.id == BrokenKeSilo.byproduct_stock_id)
            .join(PolishingProcess, PolishingProcess.id == ByproductStock.source_id)
            .where(BrokenKeSilo.silo_id == silo_c_id,
                   PolishingProcess.kode_proses.in_((kode_a, kode_b)))
            .group_by(ByproductStock.source_id)
        )).all()
        assert len(sumber_berat) == 2
        assert sorted(float(row[1]) for row in sumber_berat) == [975, 1_000]


async def test_picker_broken_menyertakan_sisa_proses_selesai(pg, sosoh):
    """Broken yang dikemas otomatis setelah proses selesai tetap tersedia
    sebagai bahan, walau belum punya baris stok terpisah. Saat dipindah,
    hasilnya dibukukan untuk rekonsiliasi ledger."""
    from app.models import User
    from app.web.api import broken_proses_tersedia
    from app.penggilingan.gudang2.service import (
        hitung_stok_silo, masukkan_stok_broken_pemilik_ke_silo)

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        daftar = await broken_proses_tersedia(user=u)
    assert len(daftar) == 1 and daftar[0]["value"] == "pemilik|pabrik", daftar
    assert "8.000 kg" in daftar[0]["label"]

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await masukkan_stok_broken_pemilik_ke_silo(
            db, user=u, jasa_id=None, nama_silo="C", berat_kg=2_000)
        assert await hitung_stok_silo(db, sosoh["silo"]["C"]) == 2_000


async def test_picker_satukan_broken_lintas_proses_tapi_pisah_pemilik(pg, sosoh):
    """Tumpukan menggabungkan banyak proses dari pemilik yang sama, tetapi
    pilihan pemilik berbeda tetap terpisah.
    """
    from app.database import now_local
    from app.models import Jasa, Pelanggan, User, ByproductStock
    from app.web.api import broken_proses_tersedia

    await _curah(pg, sosoh, 250)
    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        pel = Pelanggan(nama_pelanggan="Pemilik Broken Terpisah")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-UJI-BROKEN-AGG", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.flush()
        now = now_local()
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=sosoh["proc_id"], berat_kg=80,
                              tanggal=now.date(), waktu=now, input_by=u.id,
                              jasa_id=jasa.id))
        await db.commit()
        daftar = await broken_proses_tersedia(user=u)

    assert {item["value"] for item in daftar} == {"pemilik|pabrik", f"pemilik|{jasa.id}"}
    labels = {item["value"]: item["label"] for item in daftar}
    # Hasil otomatis proses selesai ikut digabung, setelah mengurangi yang
    # sudah tercatat untuk pemilik bawaan. Baris 80 kg milik jasa tak terpakai
    # saat menghitung stok pabrik.
    assert "8.000 kg" in labels["pemilik|pabrik"]
    assert "80 kg" in labels[f"pemilik|{jasa.id}"]


async def test_pemilik_agregat_tetap_melarang_proses_memakai_broken_sendiri(pg, sosoh):
    from app.database import now_local
    from app.models import ByproductStock, User
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_stok_broken_pemilik_ke_silo

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        active = PolishingProcess(kode_proses="POL-UJI-SELF-BROKEN", status="proses",
                                  waktu_mulai=now_local(), created_by=u.id)
        db.add(active)
        await db.flush()
        silo_id = sosoh["silo"]["C"]
        db.add(PolishingSiloUsage(polishing_process_id=active.id, silo_id=silo_id,
                                  berat_awal_kg=100, berat_akhir_kg=None,
                                  berat_terpakai_kg=100))
        now = now_local()
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=active.id, berat_kg=100,
                              tanggal=now.date(), waktu=now, input_by=u.id))
        await db.commit()
        with pytest.raises(Gudang2Error, match="SEDANG memakai Silo"):
            await masukkan_stok_broken_pemilik_ke_silo(
                db, user=u, jasa_id=None, nama_silo="C", berat_kg=8_100)


async def test_skenario_20_ton_pk_tambah_77kg_broken_ke_sosoh(pg, pemakai, pemasok):
    """Simulasi laporan lapangan: 20 t PK dari dua pemasok, proses memakai
    Silo A+B masing-masing 5 t, lalu menambah 77 kg broken dari stok lama
    (3 karung × 50 kg + 17 kg curah). Sesudahnya harus tersisa 1 karung +
    40 kg curah; neraca hasil proses mengikuti persentase yang diminta.
    """
    from sqlalchemy import func, select

    from app.database import now_local
    from app.models import (ByproductStock, FinishedGoodsStock, PolishingOutputLog,
                            ProductSku, Silo, Supplier, User, Warehouse)
    from app.penggilingan.gudang2.models import (PkGudang2Intake, PkPurchaseBatch,
                                                  PolishingProcess, PolishingSiloUsage)
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     rendemen_proses,
                                                     selesai_penyosohan,
                                                     tambah_silo_penyosohan)
    from app.penggilingan.gudang2.service import (hitung_stok_silo,
                                                   masukkan_broken_ke_silo)
    from app.penggilingan.inventory.finished_goods import (catat_broken,
                                                           catat_packing,
                                                           hitung_stok_broken_curah)
    from app.services.seed import seed_master
    from app.web.api import broken_proses_tersedia

    await seed_master()
    async with pg() as db:
        wh = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if wh is None:
            wh = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(wh)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.role = "superadmin"
        u.default_warehouse_id = wh.id
        supplier1 = await db.get(Supplier, pemasok.id)
        supplier2 = Supplier(nama_supplier="Pemasok Skenario Broken")
        db.add(supplier2)
        await db.flush()

        silos = {}
        for letter, kind in (("A", "pk"), ("B", "pk"), ("C", "broken"),
                             ("D", "pk"), ("E", "pk")):
            s = (await db.execute(select(Silo).where(
                Silo.warehouse_id == wh.id, Silo.nama_silo == f"Silo {letter}"
            ))).scalars().first()
            if s is None:
                s = Silo(warehouse_id=wh.id, nama_silo=f"Silo {letter}",
                         jenis_isi=kind, status="kosong")
                db.add(s)
                await db.flush()
            silos[letter] = s

        # 20 ton persediaan PK: 10 ton dari tiap pemasok. A/D milik supplier
        # pertama, B/E milik supplier kedua; proses contoh hanya mengambil A+B.
        for supplier, letters, suffix in ((supplier1, ("A", "D"), "S1"),
                                          (supplier2, ("B", "E"), "S2")):
            for letter in letters:
                batch = PkPurchaseBatch(
                    kode_batch=f"PK-SKENARIO-{suffix}-{letter}",
                    supplier_id=supplier.id, jasa_id=None, berat_total_kg=5_000,
                    tanggal_pembelian=now_local().date(), waktu_pembelian=now_local(),
                    input_by=u.id, status_batch="di_silo", flag_unverified=False,
                    sumber_berat="timbangan")
                db.add(batch)
                await db.flush()
                db.add(PkGudang2Intake(
                    sumber_tipe="beli_luar", pk_purchase_batch_id=batch.id,
                    tujuan="silo", silo_id=silos[letter].id, berat_kg=5_000,
                    bobot_final=True, tanggal_masuk=now_local().date(),
                    waktu_masuk=now_local(), input_by=u.id))

        # Broken 167 kg berasal dari proses terdahulu yang sudah selesai.
        sumber = PolishingProcess(
            kode_proses="POL-SKENARIO-BROKEN", status="selesai",
            waktu_mulai=now_local(), waktu_selesai=now_local(), created_by=u.id)
        db.add(sumber)
        await db.flush()
        db.add(PolishingOutputLog(
            polishing_process_id=sumber.id, jenis="broken", berat_kg=167,
            waktu_update=now_local(), input_by=u.id))
        await db.commit()
        uid, kode_sumber = u.id, sumber.kode_proses

    async with pg() as db:
        u = await db.get(User, uid)
        await catat_packing(db, user=u, kode_pol=kode_sumber, kategori="broken",
                            material_kode="putih", ukuran=50, jumlah_karung=3)
        await catat_broken(db, user=u, kode_pol=kode_sumber, berat_kg=17)

    async with pg() as db:
        u = await db.get(User, uid)
        daftar = await broken_proses_tersedia(user=u)
        assert len(daftar) == 1 and daftar[0]["value"] == "pemilik|pabrik", daftar
        from app.penggilingan.gudang2.service import masukkan_stok_broken_pemilik_ke_silo
        pindah = await masukkan_stok_broken_pemilik_ke_silo(
            db, user=u, jasa_id=None, nama_silo="C", berat_kg=77)
        assert pindah.dibongkar_dari_karung_kg == 100

    async with pg() as db:
        u = await db.get(User, uid)
        assert await hitung_stok_silo(db, silos["C"].id) == 77
        proses = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        assert proses.berat_awal_total == 10_000
        ditambah = await tambah_silo_penyosohan(
            db, user=u, kode=proses.proc.kode_proses, nama_silos=["C"])
        assert ditambah.berat_awal_total == 77

        bahan = 10_077.0
        hasil = {
            "bekatul": bahan * 0.12,
            "reject": bahan * 0.015,
            "menir": bahan * 0.01,
            "medium": bahan * 0.835,
        }
        for jenis, kg in hasil.items():
            await catat_output(db, user=u, kode=proses.proc.kode_proses,
                               jenis=jenis, berat_kg=kg)
        for letter in ("A", "B", "C"):
            await selesai_penyosohan(db, user=u, kode=proses.proc.kode_proses,
                                     nama_silo=letter, sisa_kg=0)

        assert await rendemen_proses(db, proses.proc.id) == pytest.approx(83.5)
        usage_total = (await db.execute(
            select(func.sum(PolishingSiloUsage.berat_terpakai_kg))
            .where(PolishingSiloUsage.polishing_process_id == proses.proc.id)
        )).scalar_one()
        assert float(usage_total) == pytest.approx(10_077)

        sisa_karung = (await db.execute(
            select(func.sum(FinishedGoodsStock.jumlah_karung))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(FinishedGoodsStock.source_id == sumber.id,
                   ProductSku.kategori == "broken")
        )).scalar_one()
        berat_karung = (await db.execute(
            select(func.sum(FinishedGoodsStock.berat_total_kg))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(FinishedGoodsStock.source_id == sumber.id,
                   ProductSku.kategori == "broken")
        )).scalar_one()
        sisa_curah = await hitung_stok_broken_curah(db)
        sisa_silo = await hitung_stok_silo(db, silos["C"].id)

    assert int(sisa_karung) == 1 and float(berat_karung) == pytest.approx(50)
    assert sisa_curah == pytest.approx(40)
    assert sisa_silo == pytest.approx(0)


async def test_bukukan_otomatis_dari_hasil_mesin_belum_tercatat(pg, sosoh):
    """Laporan lapangan 10 Oktober 2026: proses dengan 8.000 kg broken di
    mesin (`polishing_output_logs`, fixture `sosoh`) tapi 0 kg lewat "Catat
    broken (curah)" — SEBELUM perbaikan ini, borang "Masukkan broken ke
    silo" menjawab "(belum ada)" walau brokennya nyata ada. Di sini TANPA
    memanggil `_curah` sama sekali: `masukkan_broken_ke_silo` sendiri wajib
    membukukan dulu sebanyak yang dibutuhkan dari hasil mesin yang belum
    tercatat, SEBELUM membongkar karung — fisiknya memang begitu, hasil
    mentah yang belum ditimbang masih longgar (curah).
    """
    from app.models import User
    from app.penggilingan.gudang2.service import masukkan_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import (_broken_dibukukan,
                                                           hitung_stok_broken_curah)
    from app.services.stok import output_sosoh

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        r = await masukkan_broken_ke_silo(
            db, user=u, kode_pol=sosoh["kode_pol"], nama_silo="C", berat_kg=1_200)
    assert r.moved_kg == 1_200
    assert r.dibongkar_dari_karung_kg == 0, "cukup dari hasil mesin, tak perlu bongkar karung"

    async with pg() as db:
        # 1.200 kg dibukukan otomatis lalu LANGSUNG dipindah semua ke silo —
        # tak ada sisa curah yang menganggur di stok.
        assert await hitung_stok_broken_curah(db) == 0
        keluar_mesin = (await output_sosoh(db, sosoh["proc_id"])).get("broken")
        dibukukan = await _broken_dibukukan(db, sosoh["proc_id"])
        assert keluar_mesin == 8_000
        assert dibukukan == 1_200, "hanya sebanyak yang DIBUTUHKAN, bukan seluruh 8.000 kg"


async def test_picker_menampilkan_hasil_mesin_belum_tercatat(pg, pemakai):
    """Sebangun uji di atas, tapi lewat PICKER (`broken_proses_tersedia`):
    proses sedang BERJALAN, 2.000 kg broken di mesin, 0 kg tercatat — picker
    kini wajib menawarkannya (sebelum perbaikan ini: daftar kosong)."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.services.seed import seed_master
    from app.web.api import broken_proses_tersedia

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo_pk = Silo(nama_silo="Silo A", warehouse_id=g2.id, jenis_isi="pk")
        db.add(silo_pk)
        await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        u.role = "superadmin"

        proc = PolishingProcess(kode_proses="POL-UJIH-01", status="proses",
                                waktu_mulai=now_local(), created_by=u.id)
        db.add(proc)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=proc.id, silo_id=silo_pk.id,
                                  berat_awal_kg=5_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=5_000))
        db.add(PolishingOutputLog(polishing_process_id=proc.id, jenis="broken",
                                  berat_kg=2_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()
        kode, uid = proc.kode_proses, u.id

    async with pg() as db:
        u = await db.get(User, uid)
        daftar = await broken_proses_tersedia(user=u)
    assert len(daftar) == 1 and daftar[0]["value"] == "pemilik|pabrik", daftar
    assert "2.000" in daftar[0]["label"]
