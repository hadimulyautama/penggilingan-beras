"""Aksi KEEMPAT di jalur peristiwa: pemindahan PK Gudang 1 → Gudang 2.

Satu aksi, dua kejadian dalam SATU transaksi: `pk_dipindah_g1g2` (transfer)
lalu `pk_masuk_g2` (pemasukan, sudah di jalur peristiwa sejak aksi ketiga).
Pembatalan transfer melewati penjaga hilir milik pemasukan (P-K-10), lalu
kedua-duanya dibatalkan dengan peristiwa lawan. Cermin transfer TIDAK
dihapus — ditandai `dibatalkan`, karena semua pembacanya menyaring status.
Skenario r03 (dua staf mengirim "semua" bersamaan) dijalankan ulang.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pabrik(pg, pemasok):
    """Gudang 1 (Silo A) + Gudang 2 (Silo A/B), satu admin, satu giling
    selesai dengan 6.000 kg PK siap kirim (progres operator, belum diverifikasi)."""
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch, Silo, User,
                            Warehouse)
    from hmu_identitas import peran as P

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        s1 = Silo(nama_silo="Silo A", warehouse_id=g1.id)
        db.add_all([s1, Silo(nama_silo="Silo A", warehouse_id=g2.id), Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        u = User(nama="Elfira", role=P.ADMIN, status="aktif", default_warehouse_id=g1.id)
        db.add(u)
        await db.flush()
        kini = datetime.now(timezone.utc)
        b = PurchaseBatch(kode_batch="GB-UJI-01", supplier_id=pemasok.id, tanggal_pembelian=kini.date(),
                          waktu_pembelian=kini, berat_total_kg=10_000, kondisi_gabah="kering",
                          input_by=u.id, status_batch="digiling")
        db.add(b)
        await db.flush()
        proc = MillingProcess(kode_proses="LOT-UJI-01", status="selesai", silo_id=s1.id,
                              purchase_batch_id=b.id, berat_gabah_masuk_kg=10_000,
                              waktu_mulai=kini - timedelta(hours=8), waktu_selesai=kini - timedelta(hours=1),
                              created_by=u.id)
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id, waktu_update=kini - timedelta(hours=1),
                                  berat_kumulatif_kg=6_000, input_by=u.id))
        await db.commit()
        return {"user_id": u.id, "kode": "LOT-UJI-01", "proc_id": proc.id}


async def _kirim(pg, user_id, kode, tujuan="silo_b", berat=None) -> str:
    from app.models import User
    from app.services.transfer import TransferError, create_internal_transfer

    async with pg() as db:
        u = await db.get(User, user_id)
        try:
            r = await create_internal_transfer(db, user=u, kode_proses=kode, lokasi_tujuan=tujuan, berat=berat)
        except TransferError as e:
            return f"DITOLAK: {e}"
        return f"OK {r.transfer.kode_transfer} {float(r.transfer.berat_kg):.0f}"


async def _undo(pg, user_id) -> str:
    from app.models import User
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, user_id)
        ids, label = await svc.resolve_actor_ids(db, scope="saya", nama=None, self_id=u.id)
        try:
            return await svc.undo_last(db, actor=u, actor_ids=ids, scope_label=label)
        except svc.UndoError as e:
            return f"UndoError: {e}"


async def _hitung(pg, sql, **kw):
    async with pg() as db:
        return (await db.execute(text(sql), kw)).scalar_one()


async def _saldo(pg, proc_id) -> float:
    from app.services.transfer import saldo_pk

    async with pg() as db:
        return await saldo_pk(db, proc_id)


async def _stok_silo_g2(pg, huruf) -> float:
    from app.penggilingan.gudang2.service import get_g2_silo, hitung_stok_silo

    async with pg() as db:
        return await hitung_stok_silo(db, (await get_g2_silo(db, huruf)).id)


async def test_transfer_menulis_dua_peristiwa_dalam_satu_transaksi(pg, pabrik):
    from app.models import InternalTransfer, Peristiwa, PkGudang2Intake, ProyeksiTransferPk

    h = await _kirim(pg, pabrik["user_id"], pabrik["kode"])
    assert h.startswith("OK TRF-"), h
    async with pg() as db:
        ev = (await db.execute(select(Peristiwa).order_by(Peristiwa.id))).scalars().all()
        assert [e.jenis for e in ev] == ["pk_dipindah_g1g2", "pk_masuk_g2"]
        assert ev[0].muatan["berat_kg"] == 6000 and ev[0].muatan["lokasi_tujuan"] == "silo_b"
        assert ev[1].muatan["sumber_tipe"] == "transfer_internal"
        p = await db.get(ProyeksiTransferPk, ev[0].id)
        assert p.status == "tercatat" and p.kode_proses == pabrik["kode"] and p.intake_peristiwa_id == ev[1].id
        t = (await db.execute(select(InternalTransfer))).scalars().one()
        assert t.peristiwa_id == ev[0].id and t.status == "terkirim"
        it = (await db.execute(select(PkGudang2Intake))).scalars().one()
        assert it.internal_transfer_id == t.id and it.peristiwa_id == ev[1].id
    assert await _saldo(pg, pabrik["proc_id"]) == 0
    assert await _stok_silo_g2(pg, "B") == 6_000


async def test_r03_dua_staf_mengirim_semua_bersamaan(pg, pabrik):
    """Hanya satu yang terkirim; yang lain ditolak dengan kalimat, bukan galat
    basis data. Stok Gudang 2 = 6.000, bukan 12.000."""
    from app.models import User
    from hmu_identitas import peran as P

    async with pg() as db:
        u2 = User(nama="Eka", role=P.ADMIN, status="aktif")
        db.add(u2)
        await db.commit()
        eka = u2.id
    h = await asyncio.gather(_kirim(pg, pabrik["user_id"], pabrik["kode"]), _kirim(pg, eka, pabrik["kode"]))
    assert sum(x.startswith("OK") for x in h) == 1, h
    assert all(x.startswith("OK") or x.startswith("DITOLAK") for x in h), h
    assert await _stok_silo_g2(pg, "B") == 6_000
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='pk_dipindah_g1g2'") == 1


async def test_batal_transfer_adalah_peristiwa_lawan_dan_cermin_tak_dihapus(pg, pabrik):
    from app.models import InternalTransfer

    await _kirim(pg, pabrik["user_id"], pabrik["kode"])
    h = await _undo(pg, pabrik["user_id"])
    assert "Dibatalkan" in h and "transfer" in h.lower()
    async with pg() as db:
        t = (await db.execute(select(InternalTransfer))).scalars().one()
        assert t.status == "dibatalkan"                    # cermin TETAP ADA
        jenis = [r[0] for r in (await db.execute(text("SELECT jenis FROM peristiwa ORDER BY id"))).all()]
    assert jenis == ["pk_dipindah_g1g2", "pk_masuk_g2", "pk_masuk_g2_dibatalkan", "pk_dipindah_g1g2_dibatalkan"]
    assert await _hitung(pg, "SELECT count(*) FROM pk_gudang2_intakes") == 0
    assert await _hitung(pg, "SELECT count(*) FROM proyeksi_transfer_pk WHERE status='dibatalkan'") == 1
    assert await _saldo(pg, pabrik["proc_id"]) == 6_000                  # stok siap kirim kembali
    assert await _stok_silo_g2(pg, "B") == 0
    assert "UndoError" in await _undo(pg, pabrik["user_id"])
    # Bisa dikirim lagi sesudahnya.
    assert (await _kirim(pg, pabrik["user_id"], pabrik["kode"], berat=2_000)).startswith("OK")


async def test_batal_transfer_ditolak_bila_pk_nya_sudah_dipoles(pg, pabrik):
    from app.models import ActivityLog, User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.services import undo as svc

    await _kirim(pg, pabrik["user_id"], pabrik["kode"])
    async with pg() as db:
        u = await db.get(User, pabrik["user_id"])
        await mulai_penyosohan(db, user=u, nama_silos=["B"])
    async with pg() as db:
        log = (await db.execute(select(ActivityLog).where(ActivityLog.table_name == "internal_transfers"))).scalars().one()
        with pytest.raises(svc.UndoError) as e:
            await svc._undo_one(db, log)
    assert "dipoles" in str(e.value)
    assert await _hitung(pg, "SELECT count(*) FROM internal_transfers WHERE status='terkirim'") == 1
    assert await _stok_silo_g2(pg, "B") == 6_000


async def test_gagal_di_tengah_tak_menyimpan_apa_pun(pg, pabrik, monkeypatch):
    from app.penggilingan.gudang2 import service

    async def meledak(*a, **k):
        raise RuntimeError("uji: gagal saat pemasukan")

    monkeypatch.setattr(service, "log_activity", meledak)
    with pytest.raises(RuntimeError):
        await _kirim(pg, pabrik["user_id"], pabrik["kode"])
    for t in ("peristiwa", "proyeksi_transfer_pk", "internal_transfers", "pk_gudang2_intakes"):
        assert await _hitung(pg, f"SELECT count(*) FROM {t}") == 0, t
    assert await _saldo(pg, pabrik["proc_id"]) == 6_000
    monkeypatch.undo()
    assert (await _kirim(pg, pabrik["user_id"], pabrik["kode"])).startswith("OK")


async def test_bangun_ulang_sama_dengan_keadaan_hidup(pg, pabrik):
    from app.services import peristiwa as P

    await _kirim(pg, pabrik["user_id"], pabrik["kode"], berat=2_000)
    await _kirim(pg, pabrik["user_id"], pabrik["kode"], berat=1_000, tujuan="ditumpuk")
    await _undo(pg, pabrik["user_id"])

    async def potret():
        async with pg() as db:
            return [tuple(r) for r in (await db.execute(text(
                "SELECT peristiwa_id, kode_transfer, milling_process_id, berat_kg, lokasi_tujuan, "
                "status, dibatalkan_peristiwa_id, intake_peristiwa_id FROM proyeksi_transfer_pk "
                "ORDER BY peristiwa_id"))).all()]

    hidup = await potret()
    assert [r[5] for r in hidup] == ["tercatat", "dibatalkan"]
    async with pg() as db:
        laporan = await P.bangun_ulang(db)
    assert laporan["proyeksi_transfer_pk"] == 2 and laporan["proyeksi_pk_masuk_g2"] == 2
    assert await potret() == hidup
