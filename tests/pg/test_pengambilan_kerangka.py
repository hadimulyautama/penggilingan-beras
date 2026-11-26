"""Prototype tidak menerbitkan UUID/draf dan tidak memperluas pintu Admin."""
import json
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from tests.pg.test_halaman_bertahap import _sidik
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role',['admin','operator'])
async def test_neutral_then_native_authority(pg,gudang,monkeypatch,role):
    c=await _klien(pg,gudang['adm' if role=='admin' else 'op'],'pj-'+role,mode=role)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with c:
        before=await _sidik(pg);stock=await _stok(pg,gudang)
        source=await c.get('/barang-keluar',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert source.status_code==200
        node=BeautifulSoup(source.text,'html.parser').select_one('#padi-pengambilan-kerangka')
        assert bool(node)==(role=='admin')
        if node:
            data=json.loads(node.string);soup=BeautifulSoup(data['html'],'html.parser')
            root=soup.select_one('[data-editor-perintah="__PJ_ID__"][data-jenis="jasa"]');assert root
            assert root.select_one('h1').text=='Pengambilan barang jasa'
            assert not soup.select('script[src*="editor-perintah.js"]')
            assert json.loads(soup.select_one('#draf-awal').string)=={'revisi':0,'isi':{'jenis':'jasa','pelanggan':''}}
            assert soup.select_one('[data-pj-retry]') and soup.select_one('[data-pj-native-original][data-utuh]')
        fresh=await c.get('/barang-keluar/pengambilan-jasa?pelanggan_id=123',headers={'X-Pindah':'1'})
        assert fresh.status_code==(200 if role=='admin' else 403)
        if role=='admin':
            soup=BeautifulSoup(fresh.text,'html.parser');assert soup.select_one('[data-editor-perintah]')['data-editor-perintah']!='__PJ_ID__'
            assert json.loads(soup.select_one('#draf-awal').string)=={'revisi':0,'isi':{'jenis':'jasa','pelanggan':'123'}}
            assert soup.select_one('script[src*="editor-perintah.js"]')
        assert await _sidik(pg)==before and await _stok(pg,gudang)==stock

@pytest.mark.parametrize('url,allowed',[
 ('/barang-keluar/pengambilan-jasa',True),('/barang-keluar/pengambilan-jasa?pelanggan_id=1',True),
 ('/barang-keluar/pengambilan-jasa?pelanggan_id=',True),('/barang-keluar/pengambilan-jasa?pelanggan_id=0',False),
 ('/barang-keluar/pengambilan-jasa?pelanggan_id=1&pelanggan_id=2',False),('/barang-keluar/pengambilan-jasa?pelanggan_id=2147483648',False),
 ('/barang-keluar/pengambilan-jasa?buka=1',False),('/barang-keluar/baru',False),('/barang-keluar/draf/abc',False),
 ('//other.invalid/barang-keluar/pengambilan-jasa',False),('/barang-keluar/pengambilan-jasa#form',False)])
async def test_only_new_jasa_open(url,allowed):
    from app.web.pengambilan_kerangka import alamat_kerangka
    assert alamat_kerangka(url) is allowed
