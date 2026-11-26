"""Pintu baca netral; stok, hak dan editor native tetap otoritatif."""
import json
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role',['admin','operator'])
async def test_neutral_source_and_native_authority(pg,gudang,monkeypatch,role):
    c=await _klien(pg,gudang['adm' if role=='admin' else 'op'],'ku-'+role,mode=role)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with c:
        before=await _sidik(pg);stock=await _stok(pg,gudang)
        source=await c.get('/barang-keluar',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        node=BeautifulSoup(source.text,'html.parser').select_one('#padi-ku-kerangka');assert node
        data=json.loads(node.string);soup=BeautifulSoup(data['html'],'html.parser');root=soup.select_one('[data-ku-shell]');assert root
        assert not root.has_attr('data-kemas-ulang')
        assert all(x.has_attr('disabled') for x in root.select('form input,form select,form button'))
        assert len(root.select('form input,form select,form button'))==8
        assert not root.select('select option[value]:not([value=""])')
        assert 'Produk dan pemilik belum dibaca.' in root.text
        assert 'Tidak ada stok bebas' not in root.text
        assert not soup.select('script[src*="kemas-ulang.js"]')
        for script in ('engine','reader'):
            from app.web.kemas_ulang_kerangka import aset
            assert aset()[script] in soup.text or aset()[script] in data['html']
        fresh=await c.get('/stok-produk/kemas-ulang',params={'sku_id':gudang['sku'],'std_id':gudang['std']},headers={'X-Pindah':'1'})
        assert fresh.status_code==200
        native=BeautifulSoup(fresh.text,'html.parser');assert native.select_one('[data-kemas-ulang]')
        assert native.select_one('script[src*="kemas-ulang.js"]')
        assert not native.select_one('[data-ku-shell]')
        invalid=await c.get('/stok-produk/kemas-ulang?sku_id=2147483647',headers={'X-Pindah':'1'});assert invalid.status_code==404
        assert await _sidik(pg)==before and await _stok(pg,gudang)==stock

@pytest.mark.parametrize('url,allowed',[
 ('/stok-produk/kemas-ulang?sku_id=1',True),('/stok-produk/kemas-ulang?sku_id=1&std_id=2&jasa_id=3',True),
 ('/stok-produk/kemas-ulang?sku_id=1&kembali_stok=%2Fstok',True),
 ('/stok-produk/kemas-ulang',False),('/stok-produk/kemas-ulang?sku_id=0',False),
 ('/stok-produk/kemas-ulang?sku_id=2147483648',False),('/stok-produk/kemas-ulang?sku_id=1&sku_id=2',False),
 ('/stok-produk/kemas-ulang?sku_id=1&std_id=',False),('/stok-produk/kemas-ulang?sku_id=1&buka=1',False),
 ('//outside.invalid/stok-produk/kemas-ulang?sku_id=1',False),('/stok-produk/kemas-ulang?sku_id=1#edit',False),
 ('/api/kemas-ulang?sku_id=1',False)])
async def test_exact_read_address(url,allowed):
    from app.web.kemas_ulang_kerangka import alamat_kerangka
    assert alamat_kerangka(url) is allowed
