"""Pesanan jasa pelanggan yang sama digabung OTOMATIS saat bertemu fisik —
keputusan pemilik 10 Oktober 2026, contoh konkretnya sendiri:

"di gudang 1. di silo a ada barang milik catur, lalu di dryer juga ada
barang milik catur yang sudah kering dan sudah dingin. harus bisa dicampur
ke silo a juga. jika silo a sedang diproses berarti bahan bakunya
digabung. dan juga misalnya sedang proses silo a mili catur lalu di silo b
juga milik catur, maka bisa di mix. untuk gudang 2 juga harus bisa seperti
itu."

Catur sering datang dua kali (dua `Jasa` administratif terpisah), dan
pelanggan yang sama bertemu fisik di satu silo/dryer/proses BUKAN
pelanggaran "larangan campur pemilik" — `pastikan_satu_pemilik()`
menggabungkan keduanya (`gabung_jasa()`), bukan menolaknya. Pelanggan
BERBEDA tetap ditolak sekeras sebelumnya; pabrik tercampur jasa juga.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dunia(pg, pemakai):
    """Dua pelanggan: Catur (dua pesanan terpisah, `jasa1`+`jasa2`) dan Budi
    (satu pesanan, `jasa3` — dipakai membuktikan pelanggan beda TETAP ditolak).
    Gudang 1 (Silo A/B + 1 dryer) dan Gudang 2 (Silo C/D) tersedia."""
    from sqlalchemy import select

    from app.models import Dryer, Jasa, Pelanggan, Silo, User, Warehouse
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo = {}
        for huruf, wh in (("A", g1), ("B", g1), ("C", g2), ("D", g2)):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}", Silo.warehouse_id == wh.id
            ))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=wh.id, status="kosong")
                db.add(s)
                await db.flush()
            silo[huruf] = s.id
        dryer = (await db.execute(select(Dryer).where(
            Dryer.warehouse_id == g1.id))).scalars().first()
        if dryer is None:
            dryer = Dryer(nama="Dryer 1", warehouse_id=g1.id,
                          kapasitas_kg=50_000, status="aktif")
            db.add(dryer)
            await db.flush()

        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        u.role = "superadmin"

        catur = Pelanggan(nama_pelanggan="Catur")
        budi = Pelanggan(nama_pelanggan="Budi")
        db.add_all([catur, budi])
        await db.flush()
        jasa1 = Jasa(kode="JAS-2610-301", pelanggan_id=catur.id, status="berjalan")
        jasa2 = Jasa(kode="JAS-2610-302", pelanggan_id=catur.id, status="berjalan")
        jasa3 = Jasa(kode="JAS-2610-303", pelanggan_id=budi.id, status="berjalan")
        db.add_all([jasa1, jasa2, jasa3])
        await db.commit()
        return {"user": u.id, "g1": g1.id, "g2": g2.id, "dryer": dryer.id,
                "silo": silo, "catur": catur.id, "budi": budi.id,
                "jasa1": jasa1.id, "jasa2": jasa2.id, "jasa3": jasa3.id}


# ═══════════════════════ gabung_jasa() — inti pemindahan ═══════════════════════

async def test_gabung_jasa_memindahkan_lintas_tabel_dan_menandai_survivor(pg, dunia):
    from app.database import now_local
    from app.models import ByproductStock, Jasa, PurchaseBatch, User
    from app.models.jasa import BERJALAN, DIGABUNG
    from app.services.jasa import gabung_jasa

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        kini = now_local()
        db.add(PurchaseBatch(
            kode_batch="GB-GAB-01", jasa_id=dunia["jasa1"], berat_total_kg=5_000,
            kondisi_gabah="kering", tanggal_pembelian=date.today(),
            waktu_pembelian=kini, input_by=u.id, flag_unverified=False,
            sumber_berat="timbangan", status_batch="menunggu"))
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=1, berat_kg=200, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=dunia["jasa1"]))
        await db.commit()

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        await gabung_jasa(db, user=u, dari_id=dunia["jasa1"], ke_id=dunia["jasa2"])
        await db.commit()

    async with pg() as db:
        from sqlalchemy import select
        batch = (await db.execute(select(PurchaseBatch).where(
            PurchaseBatch.kode_batch == "GB-GAB-01"))).scalars().one()
        assert batch.jasa_id == dunia["jasa2"]
        byp = (await db.execute(select(ByproductStock).where(
            ByproductStock.source_id == 1))).scalars().one()
        assert byp.jasa_id == dunia["jasa2"]

        dari = await db.get(Jasa, dunia["jasa1"])
        assert dari.status == DIGABUNG
        assert dari.digabung_ke_id == dunia["jasa2"]
        assert dari.digabung_pada is not None

        ke = await db.get(Jasa, dunia["jasa2"])
        assert ke.status == BERJALAN  # survivor tak berubah statusnya


async def test_gabung_jasa_tolak_pelanggan_berbeda(pg, dunia):
    from app.models import User
    from app.services.jasa import JasaError, gabung_jasa

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(JasaError):
            await gabung_jasa(db, user=u, dari_id=dunia["jasa1"], ke_id=dunia["jasa3"])


async def test_gabung_jasa_tolak_dari_yang_sudah_tak_berjalan(pg, dunia):
    from app.models import User
    from app.services.jasa import JasaError, gabung_jasa

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        await gabung_jasa(db, user=u, dari_id=dunia["jasa1"], ke_id=dunia["jasa2"])
        await db.commit()

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(JasaError):
            # jasa1 sudah DIGABUNG -- tak bisa jadi sumber gabungan lagi.
            await gabung_jasa(db, user=u, dari_id=dunia["jasa1"], ke_id=dunia["jasa3"])


# ═══════════════════════ pastikan_satu_pemilik() — empat cabang ═══════════════════════

async def test_satu_pemilik_atau_hampa_tak_menggabung_apa_pun(pg, dunia):
    from app.models import Jasa, User
    from app.models.jasa import BERJALAN
    from app.services.jasa import pastikan_satu_pemilik

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        assert await pastikan_satu_pemilik(db, user=u, jasa_ids=[]) is None
        assert await pastikan_satu_pemilik(
            db, user=u, jasa_ids=[None, None]) is None
        assert await pastikan_satu_pemilik(
            db, user=u, jasa_ids=[dunia["jasa1"], dunia["jasa1"]]) == dunia["jasa1"]
        # Tak ada gabungan terjadi -- status keduanya tetap BERJALAN.
        j1 = await db.get(Jasa, dunia["jasa1"])
        assert j1.status == BERJALAN


async def test_dua_pesanan_pelanggan_sama_digabung_otomatis(pg, dunia):
    from app.models import Jasa, User
    from app.models.jasa import DIGABUNG
    from app.services.jasa import pastikan_satu_pemilik

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        survivor = await pastikan_satu_pemilik(
            db, user=u, jasa_ids=[dunia["jasa1"], dunia["jasa2"]])
        await db.commit()

    assert survivor == min(dunia["jasa1"], dunia["jasa2"])
    diserap = dunia["jasa2"] if survivor == dunia["jasa1"] else dunia["jasa1"]
    async with pg() as db:
        j = await db.get(Jasa, diserap)
        assert j.status == DIGABUNG
        assert j.digabung_ke_id == survivor


async def test_pabrik_tercampur_jasa_tetap_ditolak(pg, dunia):
    from app.models import User
    from app.services.jasa import JasaError, pastikan_satu_pemilik

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(JasaError):
            await pastikan_satu_pemilik(db, user=u, jasa_ids=[None, dunia["jasa1"]])


async def test_dua_pelanggan_berbeda_tetap_ditolak(pg, dunia):
    from app.models import User
    from app.services.jasa import JasaError, pastikan_satu_pemilik

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(JasaError):
            await pastikan_satu_pemilik(
                db, user=u, jasa_ids=[dunia["jasa1"], dunia["jasa3"]])


# ═══════════════ cocok_pemilik() — kembaran BACA-SAJA utk layar ═══════════════

async def test_cocok_pemilik_pelanggan_sama_beda_pesanan(pg, dunia):
    """`jasa1` & `jasa2` SAMA pelanggan (Catur), pesanan BEDA — inilah yang
    `berjalan.py` dulu salah baca sebagai "kepemilikan berbeda" (`!=
    jasa_id` apa adanya). `cocok_pemilik` TIDAK menggabungkan apa pun
    (BACA-SAJA) — beda dari `pastikan_satu_pemilik` di atas."""
    from app.services.jasa import cocok_pemilik

    async with pg() as db:
        assert await cocok_pemilik(db, dunia["jasa1"], dunia["jasa2"])
        assert await cocok_pemilik(db, dunia["jasa1"], dunia["jasa1"])
        assert await cocok_pemilik(db, None, None)
        assert not await cocok_pemilik(db, dunia["jasa1"], dunia["jasa3"])  # Budi
        assert not await cocok_pemilik(db, dunia["jasa1"], None)  # jasa vs pabrik
        assert not await cocok_pemilik(db, None, dunia["jasa1"])  # arah sebaliknya


async def test_cocok_pemilik_sentinel_pesanan_baru_tak_meledak(pg, dunia):
    """Galat lapangan 11 Oktober 2026: `berjalan.py` memakai
    `PEMILIK_BARU = "pesanan-baru"` (TEKS) sebagai `jasa_id` sementara untuk
    tiket yang belum melahirkan `Jasa` sungguhan. Sebelum perbaikan ini,
    `Jasa.id.in_({"pesanan-baru", jasa_nyata})` membuat Postgres menolak
    kueri ("operator does not exist: integer = character varying") —
    500 di SELURUH `/aksi`, bukan cuma kartu yang bersangkutan.
    """
    from app.services.berjalan import PEMILIK_BARU
    from app.services.jasa import cocok_pemilik

    async with pg() as db:
        assert not await cocok_pemilik(db, PEMILIK_BARU, dunia["jasa1"])
        assert not await cocok_pemilik(db, dunia["jasa1"], PEMILIK_BARU)
        assert not await cocok_pemilik(db, PEMILIK_BARU, None)
        assert not await cocok_pemilik(db, None, PEMILIK_BARU)


async def test_tombol_silo_g1_tak_mati_untuk_pelanggan_sama_beda_pesanan(pg, dunia):
    """`_pemilik_silo` (`berjalan.py`, menyalakan/mematikan tombol "Ke Silo
    N" di layar Antrian tunggu) wajib memakai aturan yang SAMA dengan
    `pastikan_satu_pemilik` — Silo A berisi `jasa1` (Catur), tombolnya untuk
    `jasa2` (Catur juga, pesanan lain) wajib TETAP MENYALA."""
    from app.services.berjalan import _pemilik_silo

    await _isi_silo_g1(pg, dunia, huruf="A", kode="PB-CP-01", kg=5_000,
                       jasa_id=dunia["jasa1"])

    async with pg() as db:
        sebutan, mati = await _pemilik_silo(db, dunia["silo"]["A"], dunia["jasa2"])
    assert mati == "", (
        f"tombol 'Ke Silo A' MATI untuk pelanggan yang SAMA (Catur, pesanan "
        f"lain) — padahal server akan menerimanya: {mati!r}")

    async with pg() as db:
        _, mati_budi = await _pemilik_silo(db, dunia["silo"]["A"], dunia["jasa3"])
    assert mati_budi != "", "pelanggan BERBEDA (Budi) wajib tetap ditolak"


# ═══════════════════════ Skenario lapangan: Gudang 1 ═══════════════════════

async def _isi_silo_g1(pg, dunia, *, huruf: str, kode: str, kg: float, jasa_id: int) -> None:
    from app.database import now_local
    from app.models import PurchaseBatch, SiloStorage, User

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        b = PurchaseBatch(
            kode_batch=kode, jasa_id=jasa_id, berat_total_kg=kg,
            kondisi_gabah="kering", tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, flag_unverified=False,
            sumber_berat="timbangan", status_batch="di_silo")
        db.add(b)
        await db.flush()
        db.add(SiloStorage(silo_id=dunia["silo"][huruf], purchase_batch_id=b.id,
                           tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                           input_by=u.id, status="terisi", jasa_id=jasa_id))
        await db.commit()


async def test_dua_silo_catur_digiling_bersama_walau_dua_pesanan(pg, dunia):
    """"sedang proses silo a milik catur lalu di silo b juga milik catur,
    maka bisa di mix" — langsung saat MULAI giling (bukan tambah silo)."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import start_milling

    await _isi_silo_g1(pg, dunia, huruf="A", kode="GB-MIX-A", kg=6_000,
                       jasa_id=dunia["jasa1"])
    await _isi_silo_g1(pg, dunia, huruf="B", kode="GB-MIX-B", kg=4_000,
                       jasa_id=dunia["jasa2"])

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        r = await start_milling(db, user=u, nama_silo=["A", "B"])
    assert float(r.berat_masuk) == 10_000
    assert r.proc.jasa_id in (dunia["jasa1"], dunia["jasa2"])


async def test_tambah_silo_giling_pelanggan_sama_beda_pesanan_digabung(pg, dunia):
    """Giling berjalan di Silo A (jasa1, Catur); Silo B datang belakangan,
    MILIK CATUR JUGA tapi pesanan administratif berbeda (jasa2) — harus bisa
    ditambahkan, bukan ditolak."""
    from app.models import Jasa, User
    from app.models.jasa import DIGABUNG
    from app.penggilingan.gudang1.services.milling import (start_milling,
                                                            tambah_silo_giling)

    await _isi_silo_g1(pg, dunia, huruf="A", kode="GB-TSG2-A", kg=6_000,
                       jasa_id=dunia["jasa1"])
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        r = await start_milling(db, user=u, nama_silo="A")
    assert r.proc.jasa_id == dunia["jasa1"]

    await _isi_silo_g1(pg, dunia, huruf="B", kode="GB-TSG2-B", kg=4_000,
                       jasa_id=dunia["jasa2"])
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        r2 = await tambah_silo_giling(
            db, user=u, kode_proses=r.proc.kode_proses, nama_silo="B")
    assert r2.bertambah == 4_000

    # jasa2 (silo B) diserap ke jasa1 (survivor -- id lebih kecil, proses
    # yang sudah berjalan): proses tetap satu jasa_id, bukan dua.
    async with pg() as db:
        j2 = await db.get(Jasa, dunia["jasa2"])
        assert j2.status == DIGABUNG
        assert j2.digabung_ke_id == dunia["jasa1"]


async def test_dryer_catur_bisa_dicampur_ke_silo_catur_lain(pg, dunia):
    """"di dryer juga ada barang milik catur yang sudah kering dan sudah
    dingin. harus bisa dicampur ke silo a juga" — dryer (jasa2) dibongkar ke
    Silo A yang sudah berisi gabah Catur lain (jasa1)."""
    from app.database import now_local
    from app.models import DryingLot, PurchaseBatch, SiloStorage, User
    from app.penggilingan.gudang1.services.silo import masuk_silo

    # Silo A sudah berisi gabah Catur (jasa1).
    await _isi_silo_g1(pg, dunia, huruf="A", kode="GB-DRY-A", kg=3_000,
                       jasa_id=dunia["jasa1"])

    # Lot kering+dingin Catur lain (jasa2), siap dibongkar ke silo.
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        now = now_local()
        b = PurchaseBatch(
            kode_batch="GB-DRY-LOT", jasa_id=dunia["jasa2"], berat_total_kg=2_000,
            kondisi_gabah="basah", tanggal_pembelian=date.today(),
            waktu_pembelian=now, input_by=u.id, flag_unverified=False,
            sumber_berat="timbangan", status_batch="di_dryer", dryer_id=dunia["dryer"])
        db.add(b)
        await db.flush()
        lot = DryingLot(kode_lot="PGR-DRY-01", dryer_id=dunia["dryer"],
                        jasa_id=dunia["jasa2"], target_kadar_air=14.0,
                        waktu_mulai_pengeringan=now, waktu_selesai_pengeringan=now,
                        waktu_selesai_pendinginan=now,
                        status="selesai", created_by=u.id)
        db.add(lot)
        await db.flush()
        from app.models import DryingLotBatch
        db.add(DryingLotBatch(drying_lot_id=lot.id, purchase_batch_id=b.id))
        await db.commit()
        lot_id = lot.id

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        # Harus BERHASIL (bukan ditolak) walau jasa1 != jasa2 -- Catur sama.
        await masuk_silo(db, user=u, nama_silo="A", kode_lot="PGR-DRY-01",
                         kode_batch=None, kode_gkr=None)

    async with pg() as db:
        from app.penggilingan.gudang1.services.silo import _silo_content_kg
        kg = await _silo_content_kg(db, dunia["silo"]["A"])
    assert kg == pytest.approx(5_000)  # 3.000 (sudah ada) + 2.000 (dari dryer)


# ═══════════════════════ Skenario lapangan: Gudang 2 ═══════════════════════

async def test_dua_silo_g2_catur_disosoh_bersama_walau_dua_pesanan(pg, dunia):
    """"untuk gudang 2 juga harus bisa seperti itu" -- dua silo G2, pelanggan
    sama, dua pesanan administratif berbeda, langsung saat MULAI penyosohan."""
    from app.database import now_local
    from app.models import PkPurchaseBatch, User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import _add_intake

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        for huruf, jid, kg in (("C", dunia["jasa1"], 5_000), ("D", dunia["jasa2"], 3_000)):
            batch = PkPurchaseBatch(
                kode_batch=f"PKB-MIXG2-{huruf}", jasa_id=jid, berat_total_kg=kg,
                tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                input_by=u.id)
            db.add(batch)
            await db.flush()
            await _add_intake(
                db, user=u, sumber_tipe="beli_luar", tujuan=huruf,
                berat_kg=kg, hpp_per_kg=0, tanggal=date.today(), jam=None,
                pk_purchase_batch_id=batch.id, bobot_final=True, jasa_id=jid)
        await db.commit()

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["C", "D"])
    assert r.proc.jasa_id in (dunia["jasa1"], dunia["jasa2"])
