"""Cermin BERTANDA, bukan dihapus — Tahap 3 butir "pembaca ke proyeksi".

Sejak aksi 1–5 pindah ke jalur peristiwa, buku besar dan proyeksi menyimpan
segalanya, tetapi baris CERMIN di tabel lama masih dihapus saat pembatalan
karena belasan pembaca menganggap "ada baris" = "ada barang". Sekarang:
baris cermin ditandai `dibatalkan_pada`, dan SEMUA pembaca ORM menyaringnya
di satu tempat (`app/models/cermin.py`, saringan sesi). SQL mentah (tiket
timbang, rekonsiliasi) menyaring eksplisit. Constraint unik tiket jadi
parsial supaya tiket yang pencatatannya dibatalkan bisa dicatat lagi.
Janji "tak ada baris bisnis yang dihapus" kini berlaku untuk kelima aksi.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :supplier_id, 'Pak Uji',
            'B 1 UJ', 12000, :waktu, 9800, 0, 'TERBUKA', 'AKTIF')
    RETURNING id
""")


async def _tiket(pg, kode, supplier_id, jenis="GABAH_BASAH") -> int:
    from app.database import now_local

    async with pg() as db:
        tid = (await db.execute(_SQL_TIKET, {
            "kode": kode, "tanggal": now_local().date(), "supplier_id": supplier_id, "jenis": jenis,
            "waktu": datetime.now(timezone.utc)})).scalar_one()
        await db.commit()
        return tid


@pytest.fixture
async def pabrik(pg, pemasok):
    from app.models import Silo, User, Warehouse
    from hmu_identitas import peran as P

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g1.id),
                    Silo(nama_silo="Silo A", warehouse_id=g2.id), Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        op = User(nama="Budi", role=P.OPERATOR, status="aktif", default_warehouse_id=g1.id)
        adm = User(nama="Elfira", role=P.ADMIN, status="aktif", default_warehouse_id=g2.id)
        db.add_all([op, adm])
        await db.commit()
        return {"op": op.id, "adm": adm.id}


async def _undo(pg, user_id) -> str:
    from app.models import User
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, user_id)
        c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
        try:
            return await svc.undo_last(db, actor=u, cakupan=c)
        except svc.UndoError as e:
            return f"UndoError: {e}"


async def _raw(pg, sql, **kw):
    async with pg() as db:
        return (await db.execute(text(sql), kw)).scalar_one()


# ── 1. Gabah masuk ───────────────────────────────────────────────────────

async def test_gabah_batal_tetap_ada_tapi_tak_terbaca(pg, pabrik, pemasok):
    from app.database import now_local
    from app.models import PurchaseBatch, User
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    from app.services.dashboard import _gabah_hari_ini
    from app.services.report import laporan_pembelian_gabah

    tid = await _tiket(pg, "CB1", pemasok.id)
    async with pg() as db:
        u = await db.get(User, pabrik["op"])
        kode1 = (await create_purchase_batch_dari_timbang(db, user=u, timbangan_transaksi_id=tid)).batch.kode_batch
    assert "Dibatalkan" in await _undo(pg, pabrik["op"])

    # Barisnya MASIH ADA di tabel lama, bertanda …
    assert await _raw(pg, "SELECT count(*) FROM purchase_batches WHERE dibatalkan_pada IS NOT NULL") == 1
    async with pg() as db:
        # … tetapi tak satu pun pembaca ORM melihatnya.
        assert (await db.execute(select(PurchaseBatch))).scalars().all() == []
        assert await db.get(PurchaseBatch, 1) is None
        assert kode1 not in await laporan_pembelian_gabah(db, "hari_ini")
        assert (await _gabah_hari_ini(db, now_local().date()))["total_kg"] == 0
        # Tiketnya ditawarkan lagi, dan rekonsiliasi tak menganggapnya tertaut.
        assert tid in {t["id"] for t in await tiket_masuk_aktif(db)}
        rek = await rekonsiliasi(db)
        assert all(kode1 != r.get("kode_batch") for r in rek["selisih"] + rek["revisi"] + rek["menyimpang"])
    # Tiket yang sama bisa dicatat ulang (constraint unik kini parsial).
    async with pg() as db:
        u = await db.get(User, pabrik["op"])
        kode2 = (await create_purchase_batch_dari_timbang(db, user=u, timbangan_transaksi_id=tid)).batch.kode_batch
    assert kode2 != kode1
    assert await _raw(pg, "SELECT count(*) FROM purchase_batches") == 2
    assert await _raw(pg, "SELECT count(*) FROM purchase_batches WHERE dibatalkan_pada IS NULL") == 1


async def test_jalur_pembatalan_masih_melihat_baris_batal(pg, pabrik, pemasok):
    from app.models import PurchaseBatch, User
    from app.models.cermin import TERMASUK_DIBATALKAN
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
    from app.services import undo as svc

    tid = await _tiket(pg, "CB2", pemasok.id)
    async with pg() as db:
        u = await db.get(User, pabrik["op"])
        bid = (await create_purchase_batch_dari_timbang(db, user=u, timbangan_transaksi_id=tid)).batch.id
    await _undo(pg, pabrik["op"])
    async with pg() as db:
        assert await db.get(PurchaseBatch, bid) is None
        b = (await db.execute(select(PurchaseBatch).where(PurchaseBatch.id == bid)
                              .execution_options(**{TERMASUK_DIBATALKAN: True}))).scalars().one()
        assert b.dibatalkan_pada is not None
        with pytest.raises(svc.UndoError) as e:
            await svc._undo_purchase(db, bid)
        assert "sudah dibatalkan" in str(e.value)


# ── 2. PK luar masuk ─────────────────────────────────────────────────────

async def test_pk_luar_batal_tetap_ada_tapi_tak_terbaca(pg, pabrik, pemasok):
    from app.models import PkPurchaseBatch, User
    from app.penggilingan.gudang2.service import create_pk_purchase_dari_timbang

    tid = await _tiket(pg, "CP1", pemasok.id, jenis="BERAS_PK")
    async with pg() as db:
        u = await db.get(User, pabrik["adm"])
        k1 = (await create_pk_purchase_dari_timbang(db, user=u, timbangan_transaksi_id=tid, jenis_pk="ks")).batch.kode_batch
    assert "Dibatalkan" in await _undo(pg, pabrik["adm"])
    assert await _raw(pg, "SELECT count(*) FROM pk_purchase_batches WHERE dibatalkan_pada IS NOT NULL") == 1
    async with pg() as db:
        assert (await db.execute(select(PkPurchaseBatch))).scalars().all() == []
        u = await db.get(User, pabrik["adm"])
        k2 = (await create_pk_purchase_dari_timbang(db, user=u, timbangan_transaksi_id=tid, jenis_pk="kl")).batch.kode_batch
    assert k2 != k1
    assert await _raw(pg, "SELECT count(*) FROM pk_purchase_batches") == 2


# ── 3. PK masuk Gudang 2 & 4. pindah tumpukan ─────────────────────────────

async def test_pk_masuk_dan_pindah_batal_tetap_ada_stok_benar(pg, pabrik, pemasok):
    from app.database import now_local
    from app.models import PkGudang2Intake, PkTumpukanToSilo, User
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import (_sisa_tumpukan_intake, get_g2_silo, hitung_stok_silo,
                                                 hitung_stok_tumpukan, masukkan_pk_luar,
                                                 pindah_tumpukan_ke_silo)

    async with pg() as db:
        u = await db.get(User, pabrik["adm"])
        db.add(PkPurchaseBatch(kode_batch="PKB-CB-01", supplier_id=pemasok.id, berat_total_kg=15_000,
                               tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                               input_by=u.id, status_batch="diterima", flag_unverified=True,
                               sumber_berat="manual"))
        await db.commit()
        r = await masukkan_pk_luar(db, user=u, kode="PKB-CB-01", tujuan="ditumpuk")
        iid = r.intake.id
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=iid, nama_silo="A", berat=3_000)
        assert await hitung_stok_tumpukan(db) == 12_000
    # Batalkan pemindahan
    assert "Dibatalkan" in await _undo(pg, pabrik["adm"])
    assert await _raw(pg, "SELECT count(*) FROM pk_tumpukan_to_silo") == 1
    assert await _raw(pg, "SELECT count(*) FROM pk_tumpukan_to_silo WHERE dibatalkan_pada IS NOT NULL") == 1
    async with pg() as db:
        assert (await db.execute(select(PkTumpukanToSilo))).scalars().all() == []
        assert await hitung_stok_tumpukan(db) == 15_000
        assert await _sisa_tumpukan_intake(db, iid) == 15_000
        assert await hitung_stok_silo(db, (await get_g2_silo(db, "A")).id) == 0
    # Batalkan pemasukan
    assert "Dibatalkan" in await _undo(pg, pabrik["adm"])
    assert await _raw(pg, "SELECT count(*) FROM pk_gudang2_intakes") == 1
    async with pg() as db:
        assert (await db.execute(select(PkGudang2Intake))).scalars().all() == []
        assert await hitung_stok_tumpukan(db) == 0
        b = (await db.execute(select(PkPurchaseBatch))).scalars().one()
        assert b.status_batch == "diterima"
        # Bisa dimasukkan lagi: indeks unik parsial per batch hanya menghitung yang hidup.
        u = await db.get(User, pabrik["adm"])
        r2 = await masukkan_pk_luar(db, user=u, kode="PKB-CB-01", tujuan="silo_b")
        assert r2.intake.id != iid
    assert await _raw(pg, "SELECT count(*) FROM pk_gudang2_intakes") == 2


# ── 5. Constraint & saringan terpasang ───────────────────────────────────

@pytest.mark.parametrize("indeks", [
    "uq_purchase_batches_timbangan_hidup",
    "uq_pk_purchase_batches_timbangan_hidup",
    "uq_pk_gudang2_intakes_batch",
    "uq_pk_gudang2_intakes_transfer",
])
async def test_indeks_unik_parsial_hidup_terpasang(pg, indeks):
    async with pg() as db:
        ada = (await db.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": indeks})).scalar()
    assert ada and "dibatalkan_pada IS NULL" in ada, indeks
    async with pg() as db:
        lama = (await db.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname IN "
            "('uq_purchase_batches_timbangan', 'uq_pk_purchase_batches_timbangan')"))).scalar_one()
    assert lama == 0


async def test_saringan_berlaku_untuk_keempat_model(pg):
    from app.models import cermin

    assert {m.__tablename__ for m in cermin.MODEL_CERMIN} == {
        "purchase_batches", "pk_purchase_batches", "pk_gudang2_intakes", "pk_tumpukan_to_silo"}
