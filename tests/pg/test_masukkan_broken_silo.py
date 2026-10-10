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
        kode_a, kode_b, uid = proc_a.kode_proses, proc_b.kode_proses, u.id

    # POL-A: catat 1.000 kg curah, lalu pindahkan SEMUANYA ke silo (sisa 0).
    async with pg() as db:
        from app.penggilingan.inventory.finished_goods import catat_broken
        u = await db.get(User, uid)
        await catat_broken(db, user=u, kode_pol=kode_a, berat_kg=1_000)
    async with pg() as db:
        u = await db.get(User, uid)
        await masukkan_broken_ke_silo(
            db, user=u, kode_pol=kode_a, nama_silo="C", berat_kg=1_000)

    # POL-B: catat 1.000 kg curah, SISAKAN 50 kg di silo (pindahkan 950).
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
    per_kode = {d["value"].split("|")[0]: d["label"] for d in daftar}

    assert kode_a not in per_kode, (
        f"{kode_a} curahnya sendiri sudah 0 (semua dipindah) — tak boleh "
        f"muncul lagi di picker: {per_kode.get(kode_a)}")
    assert kode_b in per_kode, f"{kode_b} masih bersisa 50 kg, wajib muncul"
    assert "50" in per_kode[kode_b], (
        f"{kode_b} wajib menyebut 50 kg (curahnya SENDIRI), bukan angka "
        f"gabungan dengan proses lain: {per_kode[kode_b]}")


async def test_picker_broken_proses_tersedia_hanya_yang_sedang_berjalan(pg, sosoh):
    """Permintaan pemilik 10 Oktober 2026: picker ini cuma menawarkan
    proses `status=="proses"` — DIBERITAHU lebih dulu bahwa itu berarti
    proses `selesai` yang masih bersisa broken (fixture `sosoh` di atas,
    8.000 kg) tak lagi muncul di sini, dan pemilik tetap memilihnya.
    """
    from app.models import User
    from app.web.api import broken_proses_tersedia

    await _curah(pg, sosoh, 1_000)  # proses "sosoh" sudah selesai, masih bersisa 7.000 kg

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        daftar = await broken_proses_tersedia(user=u)
    kode_yang_tampil = {d["value"].split("|")[0] for d in daftar}

    assert sosoh["kode_pol"] not in kode_yang_tampil, (
        f"{sosoh['kode_pol']} sudah SELESAI — picker ini kini wajib "
        f"menyembunyikannya walau masih bersisa broken: {daftar}")


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
    per_kode = {d["value"].split("|")[0]: d["label"] for d in daftar}

    assert kode in per_kode, (
        f"{kode} punya 2.000 kg broken di mesin, belum tercatat — wajib "
        f"muncul di picker walau 0 kg di byproduct_stock: {daftar}")
    assert "2.000" in per_kode[kode] and "belum dicatat" in per_kode[kode], (
        f"label wajib menyebut angkanya berasal dari hasil mesin yang "
        f"belum dicatat: {per_kode[kode]}")
