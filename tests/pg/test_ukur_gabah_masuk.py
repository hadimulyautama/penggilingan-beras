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
            ids, label = await svc.resolve_actor_ids(db, scope="saya", nama=None, self_id=u.id)
            async with hitung_kueri() as h:
                t0 = time.perf_counter()
                await svc.undo_last(db, actor=u, actor_ids=ids, scope_label=label)
                t_undo.append(time.perf_counter() - t0)
            n_undo.append(h.jumlah)
    med = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
    print(f"\nUKUR gabah_masuk: kueri catat={med(n_catat)} (semua {n_catat}) "
          f"waktu={med(t_catat) * 1000:.0f} ms; kueri undo={med(n_undo)} (semua {n_undo}) "
          f"waktu={med(t_undo) * 1000:.0f} ms")
    assert med(n_catat) < 40 and med(n_undo) < 40
