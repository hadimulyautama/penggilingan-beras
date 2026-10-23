"""Akses tanpa gudang tertutup; pilihan gudang resmi memulihkan cakupan."""
import re

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.database import now_local
from app.models import (Notification, NotificationRead, OutgoingItem, OutgoingRecord,
                        User, Warehouse)
from app.services import kabar
from hmu_identitas import peran as P
from tests.pg.test_barang_keluar import gudang, _klien, _stok

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def akses(pg, gudang):
    async with pg() as db:
        g1 = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == P.G1))
        tanpa = User(nama='Belum memilih gudang', role=P.OPERATOR, status='aktif')
        op1 = User(nama='Operator G1', role=P.OPERATOR, status='aktif', default_warehouse_id=g1.id)
        superadmin = User(nama='Super Admin', role=P.SUPERADMIN, status='aktif')
        db.add_all([tanpa, op1, superadmin]); await db.flush()
        # Histori selesai yang sah; pengujian ini tidak menjalankan transaksi keluar.
        asal = OutgoingRecord(kode='OUT-AKSES', tanggal=now_local().date(),
            waktu=now_local(), input_by=gudang['adm'], status='selesai')
        db.add(asal); await db.flush()
        db.add(OutgoingItem(outgoing_record_id=asal.id, item_type='finished_goods',
            product_sku_id=gudang['sku'], rice_quality_standard_id=gudang['std'],
            jumlah_karung=2, berat_kg=50))
        berita = {}
        for key, target, table, tipe in [
            ('g1', 'operator', 'drying_lots', 'pengeringan_telat'),
            ('g2', 'operator', 'outgoing_records', 'pengiriman'),
            ('lintas', 'operator', None, 'permintaan_pk'),
            ('admin', 'admin', None, 'harga'),
            ('umum', None, None, 'umum'),
        ]:
            n = Notification(tipe=tipe, target_role=target, table_name=table,
                record_id=asal.id if key == 'g2' else None,
                pesan=f'PESAN-AKSES-{key}', prioritas='merah' if key == 'g2' else 'kuning')
            db.add(n); await db.flush(); berita[key] = n.id
        await db.commit()
        return dict(gudang=gudang, tanpa=tanpa.id, g1=op1.id, g2=gudang['op'],
            admin=gudang['adm'], super=superadmin.id, oid=asal.id, berita=berita)


async def _csrf(c):
    return re.search(r'name="_csrf" value="([^"]+)"', (await c.get('/kabar')).text)[1]


@pytest.mark.parametrize('profil', ['tanpa', 'g1', 'g2', 'admin', 'super'])
async def test_daftar_detail_dan_filter_pengiriman_mengikuti_gudang_sah(pg, akses, profil):
    async with await _klien(pg, akses[profil], 'akses_keluar', mode=P.OPERATOR) as c:
        expected = 403 if profil in ('tanpa', 'g1') else 200
        for path in ['/barang-keluar', '/barang-keluar?status=perintah',
                     '/barang-keluar?status=selesai&q=OUT-AKSES',
                     '/barang-keluar?gudang=g2',
                     f"/barang-keluar/{akses['oid']}"]:
            r = await c.get(path)
            assert r.status_code == expected, path
            if expected == 403:
                assert 'OUT-AKSES' not in r.text
                assert 'Pilih gudang kerja' in r.text
        assert (await c.get('/retur')).status_code == (200 if profil in ('admin','super') else 403)


async def test_tanpa_gudang_tidak_bisa_membaca_atau_menandai_kabar(pg, akses):
    async with await _klien(pg, akses['tanpa'], 'akses_kabar', mode=P.OPERATOR) as c:
        for path in ['/kabar', '/kabar?tab=belum', '/kabar?jenis=pengiriman', '/kabar?gudang=g2']:
            r = await c.get(path)
            assert r.status_code == 200, path
            assert 'PESAN-AKSES-' not in r.text
            assert 'class="kb-item"' not in r.text
        assert (await c.get('/api/kabar/jumlah')).json() == {'belum':0,'merah':False,'terakhir':0}
        csrf = await _csrf(c)
        for nid in akses['berita'].values():
            assert (await c.get(f'/kabar?batas=100&sebelum={nid}')).status_code == 404
            assert (await c.post('/kabar/status',data={'_csrf':csrf,'id':nid,'status':'dibaca'})).status_code == 404
            assert (await c.post(f'/kabar/{nid}/buka',data={'_csrf':csrf})).status_code == 404
        assert (await c.post('/kabar/status',data={'_csrf':csrf,'status':'dibaca'})).status_code == 303
    async with pg() as db:
        user = await db.get(User, akses['tanpa'])
        assert await kabar.jenis_tersedia(db,user) == []
        assert await kabar.batas_histori(db,user) == 0
        assert await db.scalar(select(func.count()).select_from(NotificationRead)) == 0


async def test_pilih_gudang_resmi_berulang_tanpa_mengubah_profil_stok_atau_hak_admin(pg, akses):
    awal = await _stok(pg, akses['gudang'])
    async with await _klien(pg, akses['tanpa'], 'akses_pilih', mode=P.OPERATOR) as c:
        for gd, keys, pengiriman in [
            (P.G1, {'g1','lintas','umum'},403),
            (P.G2, {'g2','lintas','umum'},200),
            (P.G1, {'g1','lintas','umum'},403),
        ]:
            # Jalur formulir sebenarnya: bukan menimpa role/default gudang di DB.
            r = await c.post('/lihat-sebagai',data={'_csrf':await _csrf(c),'peran':f'{P.OPERATOR}:{gd}'})
            assert r.status_code == 303
            r = await c.get('/kabar')
            for key in akses['berita']:
                assert (f'PESAN-AKSES-{key}' in r.text) == (key in keys)
            badge = (await c.get('/api/kabar/jumlah')).json()
            assert badge['belum'] == len(keys)
            assert r.text.count('data-unread="true"') == badge['belum']
            assert (await c.get(f"/barang-keluar/{akses['oid']}")).status_code == pengiriman
            assert (await c.get('/retur')).status_code == 403
            assert (await c.get('/api/actions/keluar-dimuat')).status_code == 403
        r = await c.post('/lihat-sebagai',data={'_csrf':await _csrf(c),'peran':''})
        assert r.status_code == 303
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 0
        assert (await c.get('/barang-keluar')).status_code == 403
    async with pg() as db:
        u = await db.get(User, akses['tanpa'])
        assert u.default_warehouse_id is None and u.role == P.OPERATOR
        assert await db.scalar(select(func.count()).select_from(NotificationRead)) == 0
        assert (await db.get(OutgoingRecord, akses['oid'])).status == 'selesai'
    assert await _stok(pg, akses['gudang']) == awal


@pytest.mark.parametrize('gd', [P.G1,P.G2])
async def test_gudang_nonaktif_tidak_memberi_akses(pg, akses, gd):
    async with pg() as db:
        wh = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == gd))
        u = await db.get(User,akses['tanpa'])
        u.default_warehouse_id = wh.id
        wh.aktif = False
        await db.commit()
    async with await _klien(pg, akses['tanpa'], 'akses_nonaktif', mode=P.OPERATOR) as c:
        assert (await c.get('/barang-keluar')).status_code == 403
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 0


async def test_ganti_gudang_mempertahankan_status_baca_pribadi(pg, akses):
    async with await _klien(pg, akses['tanpa'], 'akses_status', mode=P.OPERATOR) as c:
        await c.post('/lihat-sebagai',data={'_csrf':await _csrf(c),'peran':f'{P.OPERATOR}:{P.G2}'})
        csrf = await _csrf(c)
        nid = akses['berita']['g2']
        assert (await c.post('/kabar/status',data={'_csrf':csrf,'id':nid,'status':'dibaca'})).status_code == 303
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 2
        await c.post('/lihat-sebagai',data={'_csrf':await _csrf(c),'peran':''})
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 0
        await c.post('/lihat-sebagai',data={'_csrf':await _csrf(c),'peran':f'{P.OPERATOR}:{P.G2}'})
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 2
        assert 'Sudah dibaca' in (await c.get('/kabar')).text
    async with pg() as db:
        other = await db.get(User,akses['g2'])
        assert await kabar.jumlah_baru(db,other) == 3


@pytest.mark.parametrize('profil', ['admin','super'])
async def test_admin_tetap_tanpa_gudang_dan_menerima_kabar_yang_sah(pg, akses, profil):
    async with await _klien(pg,akses[profil],f'akses_{profil}') as c:
        r = await c.get('/kabar')
        assert 'PESAN-AKSES-admin' in r.text and 'PESAN-AKSES-umum' in r.text
        assert 'PESAN-AKSES-g1' not in r.text and 'PESAN-AKSES-g2' not in r.text
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 2

