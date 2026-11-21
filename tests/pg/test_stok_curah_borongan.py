"""Pembacaan daftar setara dengan validasi satu proses yang tetap segar."""
import dataclasses
import pytest
from sqlalchemy import select
from app.database import now_local
from app.models import PolishingProcess, PolishingOutputLog, User
from app.services import stok
from tests.pg.test_stok_produk_jasa import sosoh_jasa, _packing

pytestmark = pytest.mark.asyncio

async def test_borongan_setara_tunggal_status_pemilik_dan_pembukuan(pg, sosoh_jasa):
    g = sosoh_jasa
    await _packing(pg, g, kode_pol=g['kode_pabrik'], karung=40)
    await _packing(pg, g, kode_pol=g['kode_jasa'], karung=20)
    async with pg() as db:
        proses = (await db.scalars(select(PolishingProcess).order_by(PolishingProcess.id))).all()
        ids = [p.id for p in proses]
        proses[-1].status = 'proses'
        proses[-1].waktu_selesai = None
        for p in proses:
            # Entri terpisah dijumlah; jenis otomatis tidak menjadi tugas packing.
            for jenis, kg in [('premium', 500), ('premium', 0.25), ('broken', 110)]:
                db.add(PolishingOutputLog(polishing_process_id=p.id, jenis=jenis,
                    berat_kg=kg, waktu_update=now_local(), input_by=g['user']))
        await db.commit()
    from app.penggilingan.inventory.finished_goods import catat_curah
    async with pg() as db:
        await catat_curah(db, user=await db.get(User, g['user']),
                         kode_pol=g['kode_pabrik'], jenis='premium')
    for final_only in [False, True]:
        async with pg() as db:
            daftar = await stok.beras_curah(db, termasuk_berjalan=not final_only)
            tunggal = []
            for pid in ids:
                tunggal.extend(await stok.beras_curah(db, proses_id=pid,
                                            termasuk_berjalan=not final_only))
            tunggal.sort(key=lambda b: (stok._URUT_BARANG.get(b.jenis, 99), b.kode_proses))
            assert daftar == tunggal
            assert not any(b.jenis == 'broken' for b in daftar)
            assert {b.jasa_id for b in daftar} == ({None} if final_only else {None, g['jasa_id']})
            assert next(b for b in daftar if b.kode_proses==g['kode_pabrik']).sisa_kg == 8000
    # Mutasi berikut tidak boleh memakai hasil daftar/saldo dari pembacaan lama.
    await _packing(pg, g, kode_pol=g['kode_pabrik'], karung=4)
    async with pg() as db:
        assert next(b for b in await stok.beras_curah(db)
                    if b.kode_proses==g['kode_pabrik']).sisa_kg == 7900
