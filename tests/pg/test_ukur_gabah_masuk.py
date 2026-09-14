"""Ukuran biaya aksi "Gabah masuk" — jumlah kueri dan waktu, dicetak (-s).

Bukan uji lulus/gagal yang ketat: yang dijaga hanya batas atas yang longgar.
Angkanya dipakai laporan Tahap 3 (sebelum vs sesudah jalur peristiwa).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES (:kode, :tanggal, 'MASUK', 'GABAH_BASAH', 'DUA_KALI', :supplier_id, 'Pak Uji',
            'B 1 UJ', 12000, :waktu, 9800, 0, 'TERBUKA', 'AKTIF')
    RETURNING id
""")


async def _tiket(db, kode, supplier_id):
    from app.database import now_local
    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": now_local().date(), "supplier_id": supplier_id,
        "waktu": datetime.now(timezone.utc)})).scalar_one()


def _med(xs):
    return sorted(xs)[len(xs) // 2]


async def test_ukur_catat_dan_batalkan(pg, pemakai, pemasok, hitung_kueri):
    from app.models import User
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
    from app.services import undo as svc

    n_catat, t_catat, n_undo, t_undo = [], [], [], []
    for i in range(5):
        async with pg() as db:
            tid = await _tiket(db, f"UK{i}", pemasok.id)
            await db.commit()
        async with pg() as db:
            u = await db.get(User, pemakai.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await create_purchase_batch_dari_timbang(db, user=u, timbangan_transaksi_id=tid,
                                                         kondisi_gabah="basah")
                t_catat.append(time.perf_counter() - t0)
            n_catat.append(h.jumlah)
        async with pg() as db:
            u = await db.get(User, pemakai.id)
            c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await svc.undo_last(db, actor=u, cakupan=c)
                t_undo.append(time.perf_counter() - t0)
            n_undo.append(h.jumlah)
    med = _med
    print(f"\nUKUR gabah_masuk: kueri catat={med(n_catat)} (semua {n_catat}) "
          f"waktu={med(t_catat) * 1000:.0f} ms; kueri undo={med(n_undo)} (semua {n_undo}) "
          f"waktu={med(t_undo) * 1000:.0f} ms")
    assert med(n_catat) < 40 and med(n_undo) < 40


_SQL_TIKET_PK = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES (:kode, :tanggal, 'MASUK', 'BERAS_PK', 'DUA_KALI', :supplier_id, 'CV PK',
            'B 9 PK', 12000, :waktu, 8000, 0, 'TERBUKA', 'AKTIF')
    RETURNING id
""")


async def test_ukur_pk_luar_catat_dan_batalkan(pg, pemasok, hitung_kueri):
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.service import create_pk_purchase_dari_timbang
    from app.services import undo as svc
    from hmu_identitas import peran as P

    async with pg() as db:
        staf = User(nama="Staf Ukur", role=P.ADMIN, status="aktif")
        db.add(staf)
        await db.commit()
        sid = staf.id
    n_catat, t_catat, n_undo, t_undo = [], [], [], []
    for i in range(5):
        async with pg() as db:
            tid = (await db.execute(_SQL_TIKET_PK, {
                "kode": f"UP{i}", "tanggal": now_local().date(), "supplier_id": pemasok.id,
                "waktu": datetime.now(timezone.utc)})).scalar_one()
            await db.commit()
        async with pg() as db:
            u = await db.get(User, sid)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await create_pk_purchase_dari_timbang(db, user=u, timbangan_transaksi_id=tid, jenis_pk="ks")
                t_catat.append(time.perf_counter() - t0)
            n_catat.append(h.jumlah)
        async with pg() as db:
            u = await db.get(User, sid)
            c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await svc.undo_last(db, actor=u, cakupan=c)
                t_undo.append(time.perf_counter() - t0)
            n_undo.append(h.jumlah)
    print(f"\nUKUR pk_luar_masuk: kueri catat={_med(n_catat)} (semua {n_catat}) "
          f"waktu={_med(t_catat) * 1000:.0f} ms; kueri undo={_med(n_undo)} (semua {n_undo}) "
          f"waktu={_med(t_undo) * 1000:.0f} ms")
    assert _med(n_catat) < 40 and _med(n_undo) < 40


async def test_ukur_pk_masuk_g2_dan_batalkan(pg, pemasok, hitung_kueri):
    from datetime import date

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.services import undo as svc
    from hmu_identitas import peran as P

    async with pg() as db:
        w = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(w)
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=w.id), Silo(nama_silo="Silo B", warehouse_id=w.id)])
        u = User(nama="Staf Ukur", role=P.ADMIN, status="aktif", default_warehouse_id=w.id)
        db.add(u)
        await db.flush()
        for i in range(5):
            db.add(PkPurchaseBatch(kode_batch=f"PKB-UKUR-{i}", supplier_id=pemasok.id, berat_total_kg=8000,
                                   tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                                   input_by=u.id, status_batch="diterima", flag_unverified=True,
                                   sumber_berat="manual"))
        await db.commit()
        sid = u.id
    n_catat, t_catat, n_undo, t_undo = [], [], [], []
    for i in range(5):
        async with pg() as db:
            u = await db.get(User, sid)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await masukkan_pk_luar(db, user=u, kode=f"PKB-UKUR-{i}", tujuan="silo_a")
                t_catat.append(time.perf_counter() - t0)
            n_catat.append(h.jumlah)
        async with pg() as db:
            u = await db.get(User, sid)
            c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await svc.undo_last(db, actor=u, cakupan=c)
                t_undo.append(time.perf_counter() - t0)
            n_undo.append(h.jumlah)
    print(f"\nUKUR pk_masuk_g2: kueri catat={_med(n_catat)} (semua {n_catat}) "
          f"waktu={_med(t_catat) * 1000:.0f} ms; kueri undo={_med(n_undo)} (semua {n_undo}) "
          f"waktu={_med(t_undo) * 1000:.0f} ms")
    assert _med(n_catat) < 40 and _med(n_undo) < 40


async def test_ukur_transfer_dan_batalkan(pg, pemasok, hitung_kueri):
    from datetime import timedelta

    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch, Silo, User,
                            Warehouse)
    from app.services import undo as svc
    from app.services.transfer import create_internal_transfer
    from hmu_identitas import peran as P

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        s1 = Silo(nama_silo="Silo A", warehouse_id=g1.id)
        db.add_all([s1, Silo(nama_silo="Silo A", warehouse_id=g2.id), Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        u = User(nama="Staf Ukur", role=P.ADMIN, status="aktif", default_warehouse_id=g1.id)
        db.add(u)
        await db.flush()
        kini = datetime.now(timezone.utc)
        for i in range(5):
            b = PurchaseBatch(kode_batch=f"GB-UKUR-{i}", supplier_id=pemasok.id, tanggal_pembelian=kini.date(),
                              waktu_pembelian=kini, berat_total_kg=10_000, kondisi_gabah="kering",
                              input_by=u.id, status_batch="digiling")
            db.add(b)
            await db.flush()
            proc = MillingProcess(kode_proses=f"LOT-UKUR-{i}", status="selesai", silo_id=s1.id,
                                  purchase_batch_id=b.id, berat_gabah_masuk_kg=10_000,
                                  waktu_mulai=kini - timedelta(hours=8), waktu_selesai=kini, created_by=u.id)
            db.add(proc)
            await db.flush()
            db.add(MillingProgressLog(milling_process_id=proc.id, waktu_update=kini,
                                      berat_kumulatif_kg=6_000, input_by=u.id))
        await db.commit()
        sid = u.id
    n_catat, t_catat, n_undo, t_undo = [], [], [], []
    for i in range(5):
        async with pg() as db:
            u = await db.get(User, sid)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await create_internal_transfer(db, user=u, kode_proses=f"LOT-UKUR-{i}", lokasi_tujuan="silo_b")
                t_catat.append(time.perf_counter() - t0)
            n_catat.append(h.jumlah)
        async with pg() as db:
            u = await db.get(User, sid)
            c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await svc.undo_last(db, actor=u, cakupan=c)
                t_undo.append(time.perf_counter() - t0)
            n_undo.append(h.jumlah)
    print(f"\nUKUR transfer_pk: kueri catat={_med(n_catat)} (semua {n_catat}) "
          f"waktu={_med(t_catat) * 1000:.0f} ms; kueri undo={_med(n_undo)} (semua {n_undo}) "
          f"waktu={_med(t_undo) * 1000:.0f} ms")
    assert _med(n_catat) < 60 and _med(n_undo) < 40


async def test_ukur_pindah_tumpukan_dan_batalkan(pg, pemasok, hitung_kueri):
    from datetime import date

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar, pindah_tumpukan_ke_silo
    from app.services import undo as svc
    from hmu_identitas import peran as P

    async with pg() as db:
        w = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(w)
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=w.id), Silo(nama_silo="Silo B", warehouse_id=w.id)])
        u = User(nama="Staf Ukur", role=P.ADMIN, status="aktif", default_warehouse_id=w.id)
        db.add(u)
        await db.flush()
        db.add(PkPurchaseBatch(kode_batch="PKB-UKUR", supplier_id=pemasok.id, berat_total_kg=50_000,
                               tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                               input_by=u.id, status_batch="diterima", flag_unverified=True,
                               sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)
        r = await masukkan_pk_luar(db, user=u, kode="PKB-UKUR", tujuan="ditumpuk")
        sid, iid = u.id, r.intake.id
    n_catat, t_catat, n_undo, t_undo = [], [], [], []
    for i in range(5):
        async with pg() as db:
            u = await db.get(User, sid)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await pindah_tumpukan_ke_silo(db, user=u, intake_id=iid, nama_silo="A", berat=1_000)
                t_catat.append(time.perf_counter() - t0)
            n_catat.append(h.jumlah)
        async with pg() as db:
            u = await db.get(User, sid)
            c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                try:
                    await svc.undo_last(db, actor=u, cakupan=c)
                except svc.UndoError:
                    pass
                t_undo.append(time.perf_counter() - t0)
            n_undo.append(h.jumlah)
    print(f"\nUKUR pindah_tumpukan_silo: kueri catat={_med(n_catat)} (semua {n_catat}) "
          f"waktu={_med(t_catat) * 1000:.0f} ms; kueri undo={_med(n_undo)} (semua {n_undo}) "
          f"waktu={_med(t_undo) * 1000:.0f} ms")
    assert _med(n_catat) < 40 and _med(n_undo) < 40
