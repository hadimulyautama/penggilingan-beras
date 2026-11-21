"""Pilihan tujuan boleh dibagi dalam GET; payload dan konteks tidak boleh ikut."""
import dataclasses

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from app import performa
from app.models import Dryer, Silo, Warehouse
from app.services.berjalan import _tujuan_gabah
from tests.pg.test_riwayat_pengeringan import pabrik

pytestmark = pytest.mark.asyncio


async def test_memo_tujuan_menjaga_payload_dan_tetap_segar(pg, pabrik):
    app = FastAPI()
    app.add_middleware(performa.PerformaMiddleware)
    sql = []

    def hitung(*args):
        sql.append(1)

    @app.api_route('/uji', methods=['GET', 'POST'])
    async def baca():
        async with pg() as db:
            awal = len(sql)
            a = await _tujuan_gabah(db, 'kering', warehouse_id=pabrik['g1'],
                                    post='/batch-a', data={'kode_batch': 'A'})
            tengah = len(sql)
            a[0].data['kode_batch'] = 'diubah'
            b = await _tujuan_gabah(db, 'kering', warehouse_id=pabrik['g1'],
                                    post='/batch-b', data={'kode_batch': 'B'})
            assert a and b and all(t.post == '/batch-b' and t.data['kode_batch'] == 'B' for t in b)
            assert {t.data['tujuan'] for t in a} == {t.data['tujuan'] for t in b}
            return {'pertama': tengah-awal, 'kedua': len(sql)-tengah}

    event.listen(Engine, 'before_cursor_execute', hitung)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji') as c:
            for _ in range(2):
                r = (await c.get('/uji')).json()
                assert r['pertama'] > 0 and r['kedua'] == 0
            r = (await c.post('/uji')).json()
            assert r['pertama'] > 0 and r['kedua'] > 0
    finally:
        event.remove(Engine, 'before_cursor_execute', hitung)


async def test_kunci_tujuan_memisah_kondisi_pemilik_tiket_dan_gudang(pg, pabrik):
    async with pg() as db:
        w = Warehouse(nama_gudang='Gudang uji pembanding', aktif=True)
        db.add(w)
        await db.flush()
        wid = w.id
        db.add(Silo(warehouse_id=wid, nama_silo='Silo pembanding', jenis_isi='gabah'))
        await db.commit()
    token = performa._konteks.set({'boleh_memo': True, 'memo': {}})
    sql = []
    def hitung(*args): sql.append(1)
    event.listen(Engine, 'before_cursor_execute', hitung)
    try:
        async with pg() as db:
            semua = []
            # ID pesanan tanpa isi hanya menguji pemisahan kunci, bukan kontrak
            # pencocokan pemilik; aturan pemilik diuji suite jasa yang ada.
            for kondisi, jasa, tiket, gudang in [
                ('kering', None, None, pabrik['g1']),
                ('basah', None, None, pabrik['g1']),
                ('kering', 987654, None, pabrik['g1']),
                ('kering', None, {'jasa': False}, pabrik['g1']),
                ('kering', None, {'jasa': True, 'pelanggan_nama': 'Uji'}, pabrik['g1']),
                ('kering', None, None, wid),
            ]:
                n = len(sql)
                a = await _tujuan_gabah(db, kondisi, jasa_id=jasa, tiket=tiket,
                                        warehouse_id=gudang, post='/uji', data={})
                assert len(sql) > n, 'Konteks lain wajib dibaca sendiri'
                b = await _tujuan_gabah(db, kondisi, jasa_id=jasa, tiket=tiket,
                                        warehouse_id=gudang, post='/uji', data={})
                assert dataclasses.asdict(a[0]) == dataclasses.asdict(b[0])
                semua.append(a)
            assert {t.data['tujuan'] for t in semua[0] if t.data['tujuan'] != 'tumpuk'}.isdisjoint(
                {t.data['tujuan'] for t in semua[-1] if t.data['tujuan'] != 'tumpuk'})
            assert any(t.utama for t in semua[1] if t.data['tujuan'].startswith('dryer:'))
    finally:
        event.remove(Engine, 'before_cursor_execute', hitung)
        performa._konteks.reset(token)


async def test_sesi_kotor_tidak_memo_dan_permintaan_baru_membaca_status(pg, pabrik):
    async with pg() as db:
        d = await db.scalar(select(Dryer).where(Dryer.warehouse_id == pabrik['g1']))
        assert d is not None
        did = d.id
        token = performa._konteks.set({'boleh_memo': True, 'memo': {}})
        try:
            a = await _tujuan_gabah(db, 'basah', warehouse_id=pabrik['g1'], post='/uji', data={})
            assert not next(t.mati for t in a if t.data['tujuan'] == f'dryer:{did}')
            d.status = 'perawatan'
            with db.no_autoflush:
                b = await _tujuan_gabah(db, 'basah', warehouse_id=pabrik['g1'], post='/uji', data={})
            assert 'perawatan' in next(t.mati for t in b if t.data['tujuan'] == f'dryer:{did}')
            await db.commit()
        finally:
            performa._konteks.reset(token)
    token = performa._konteks.set({'boleh_memo': True, 'memo': {}})
    try:
        async with pg() as db:
            c = await _tujuan_gabah(db, 'basah', warehouse_id=pabrik['g1'], post='/uji', data={})
            assert 'perawatan' in next(t.mati for t in c if t.data['tujuan'] == f'dryer:{did}')
    finally:
        performa._konteks.reset(token)
