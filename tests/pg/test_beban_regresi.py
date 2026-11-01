"""Pagar beban: seluruh catatan tetap dapat ditemukan, tanpa N+1 tersembunyi."""
import re
import pytest
from app.performa import pasang_penghitung
from tests.pg.test_portal_pelanggan import portal,qc,client
from tests.pg.test_papan_beranda_http import _klien
from tests.pg.test_beban_besar import semai

pytestmark=pytest.mark.asyncio

async def test_array_id_memiliki_hasil_sama_dengan_in_termasuk_kosong(pg,portal):
    from sqlalchemy import select
    from app.models import Jasa
    from app.performa import dalam
    async with pg() as db:
        for ids in ([],[portal.orders[0].id],[portal.orders[0].id,portal.orders[1].id,None]):
            lama=set((await db.scalars(select(Jasa.id).where(Jasa.id.in_(ids)))).all())
            baru=set((await db.scalars(select(Jasa.id).where(dalam(db,Jasa.id,ids)))).all())
            assert lama==baru

async def test_pekerjaan_berhalaman_dan_cari_meliputi_seluruh_daftar(pg,portal):
    await semai(pg,portal,120)
    pasang_penghitung(pg.kw['bind'])
    async with await _klien(pg,role='superadmin') as c:
        pages=[await c.get('/pekerjaan?halaman='+str(i)) for i in range(1,6)]
        assert all(r.status_code==200 for r in pages)
        codes=[set(re.findall(r'BM-\d{7}',r.text)) for r in pages]
        assert len(codes[0])<=50 and len(codes[1])<=50
        assert not codes[0]&codes[1]
        assert set.union(*codes)=={f'BM-{i:07}' for i in range(120)}
        assert all(int(r.headers['x-sql-count'])<150 for r in pages)
        assert 'Halaman pekerjaan' in pages[0].text
        r=await c.get('/pekerjaan?cari=BM-0000000')
        assert r.status_code==200 and 'BM-0000000' in r.text
        assert 'BM-0000119' not in r.text

async def test_riwayat_sql_tidak_memotong_atau_membocorkan_pemilik(pg,portal):
    await semai(pg,portal,120)
    pasang_penghitung(pg.kw['bind'])
    async with client(portal.accounts[0]) as c:
        pages=[await c.get('/pelanggan/riwayat-proses?halaman='+str(i)) for i in range(1,6)]
        codes=[set(re.findall(r'B[MT]-\d{7}',r.text)) for r in pages]
        expected={f'B{k}-{i:07}' for i in range(0,120,2) for k in ('M','T')}
        assert set.union(*codes)==expected
        assert sum(map(len,codes))==len(expected)
        assert all(len(x)<=25 for x in codes)
        assert all(int(r.headers['x-sql-count'])<45 for r in pages)
        r=await c.get('/pelanggan/riwayat-proses?q=BM-0000000')
        assert 'BM-0000000' in r.text and 'BM-0000002' not in r.text
        r=await c.get('/pelanggan/riwayat-proses?q=BM-0000001')
        assert 'Tidak ada hasil yang cocok' in r.text
        r=await c.get('/pelanggan/riwayat-proses?jenis=giling')
        assert not re.search(r'BT-\d{7}',r.text)

async def test_daftar_pelanggan_sql_menjaga_filter_kode_dan_status(pg,portal):
    from app.services import jasa_pelanggan as svc
    async with pg() as db:
        a=await svc.daftar(db,cari=portal.orders[0].kode)
        assert [x['id'] for x in a['kartu']]==[portal.owners[0].id]
        b=await svc.daftar(db,cari=portal.owners[1].nama_pelanggan,status='selesai')
        assert b['jumlah']==0 and b['kartu']==[]

async def test_rincian_staf_berhalaman_dan_total_tetap_lengkap(pg,portal):
    from bs4 import BeautifulSoup
    await semai(pg,portal,120)
    pid=portal.owners[0].id
    async with await _klien(pg,role='superadmin') as c:
        a=await c.get(f'/jasa/pelanggan/{pid}?tab=proses')
        b=await c.get(f'/jasa/pelanggan/{pid}?tab=proses&rincian_halaman=2')
        assert a.status_code==b.status_code==200
        s=BeautifulSoup(a.text,'html.parser')
        assert s.select_one('main nav[aria-label="Halaman catatan pelanggan"]')
        assert not s.select_one('title nav')
        codes=lambda r:set(re.findall(r'B[MT]-\d{7}',r.text))
        assert len(codes(a))<=25 and len(codes(b))<=25 and not codes(a)&codes(b)
        r=await c.get(f'/jasa/pelanggan/{pid}?tab=proses&rincian_cari=BM-0000000')
        assert 'BM-0000000' in r.text and 'BM-0000002' not in r.text
