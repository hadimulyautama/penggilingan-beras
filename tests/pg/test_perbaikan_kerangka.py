"""Pintu netral tidak membaca kiriman atau menentukan kelayakan undo."""
import json
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_perbaikan_pengiriman import selesai
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from tests.pg.test_halaman_bertahap import _sidik
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role',['admin','operator'])
async def test_pure_structure_then_fresh_authority(pg,gudang,monkeypatch,role):
    from app.web import perbaikan_kerangka as shell,perbaikan_pengiriman as native
    rid=await selesai(pg,gudang)
    c=await _klien(pg,gudang['adm' if role=='admin' else 'op'],'pp-shell-'+role,mode=role)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with c:
        before=await _sidik(pg);stock=await _stok(pg,gudang);original=shell.susun
        async def deny(*a,**kw):raise AssertionError('Prototype must not read outgoing/undo data')
        async def guarded(*a,**kw):
            with monkeypatch.context() as scoped:
                scoped.setattr(native,'konteks',deny);scoped.setattr(native,'langkah_terakhir',deny)
                return await original(*a,**kw)
        monkeypatch.setattr(shell,'susun',guarded)
        source=await c.get('/pekerjaan/catat-lain',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert source.status_code==200
        node=BeautifulSoup(source.text,'html.parser').select_one('#padi-perbaikan-kerangka');assert bool(node)==(role=='admin')
        if node:
            doc=BeautifulSoup(json.loads(node.string)['html'],'html.parser');r=doc.select_one('[data-pp-shell]');assert r and not r.select('form,[data-perbaikan-pengiriman]')
            assert r.select_one('h1').text=='Perbaiki pengiriman'
            assert all(x.has_attr('disabled') for x in r.select('input,textarea,button:not([data-pp-retry])'))
            assert not r.has_attr('data-pp-record')
        monkeypatch.setattr(shell,'susun',original)
        fresh=await c.get(f'/barang-keluar/{rid}/perbaikan',headers={'X-Pindah':'1'});assert fresh.status_code==(200 if role=='admin' else 403)
        if role=='admin':
            r=BeautifulSoup(fresh.text,'html.parser').select_one('[data-pp-native]');assert r['data-pp-record']==str(rid)
            assert r.select_one('form[data-perbaikan-pengiriman]')
        assert await _sidik(pg)==before and await _stok(pg,gudang)==stock

@pytest.mark.parametrize('url,allowed',[
 ('/barang-keluar/1/perbaikan',True),('/barang-keluar/1/perbaikan?q=uji&status=selesai&sebelum=42',True),
 ('/barang-keluar/1/perbaikan?q=a&q=b',False),('/barang-keluar/0/perbaikan',False),('/barang-keluar/2147483648/perbaikan',False),
 ('/barang-keluar/1/perbaikan?buka=1',False),('/barang-keluar/1/koreksi-selesai',False),
 ('//other.invalid/barang-keluar/1/perbaikan',False),('/barang-keluar/1/perbaikan#x',False)])
async def test_only_repair_entry(url,allowed):
    from app.web.perbaikan_kerangka import alamat_kerangka
    assert alamat_kerangka(url) is allowed
