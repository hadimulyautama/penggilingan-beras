"""Kerangka perintah eksplisit tidak membaca record atau mengarang hak/status."""
import json
from types import SimpleNamespace
from bs4 import BeautifulSoup
from fastapi import Request
import pytest
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_verifikasi_pengiriman import _setup
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from tests.pg.test_halaman_bertahap import _sidik
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio
@pytest.mark.parametrize('role',['admin','operator'])
async def test_pure_structure_then_native_permissions(pg,gudang,monkeypatch,role):
    from app.web import pengiriman_detail_kerangka as shell
    from app.services import barang_keluar as svc
    rs,_=await _setup(pg,gudang,101);record=rs[0].rec.id
    c=await _klien(pg,gudang['adm' if role=='admin' else 'op'],'pkd-'+role,mode=role)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    async with c:
        before=await _sidik(pg);stock=await _stok(pg,gudang)
        request=Request({'type':'http','method':'GET','path':'/','headers':[],'query_string':b'','state':{'portal_scope':object()}})
        assert await shell.susun(request,SimpleNamespace(user=SimpleNamespace(role='admin')),navigasi={}) is None
        original_shell=shell.susun
        async def denied(*a,**kw):raise AssertionError('Prototype must not read actual outgoing records')
        async def guarded_shell(*a,**kw):
            with monkeypatch.context() as scoped:
                scoped.setattr(svc,'daftar',denied)
                return await original_shell(*a,**kw)
        monkeypatch.setattr(shell,'susun',guarded_shell)
        source=await c.get('/pekerjaan/catat-lain',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert source.status_code==200
        node=BeautifulSoup(source.text,'html.parser').select_one('#padi-pengiriman-detail-kerangka');assert node
        data=json.loads(node.string);doc=BeautifulSoup(data['html'],'html.parser');r=doc.select_one('[data-pengiriman-detail-shell]');assert r and not r.has_attr('data-pengiriman-native')
        assert len(r.select('.detail-kirim-tabs [role=tab]'))==4 and len(r.select('[role=tabpanel]'))==4
        assert all(x.has_attr('disabled') for x in r.select('button:not([data-pkd-retry])'))
        assert not doc.select('[data-verifikasi-pengiriman],#verifikasi-awal,form')
        assert all(d.text=='—' for d in r.select('dd'))
        monkeypatch.setattr(shell,'susun',original_shell)
        response=await c.get('/barang-keluar?status=dimuat');soup=BeautifulSoup(response.text,'html.parser')
        for row in soup.select('tr.keluar-baris[data-detail-keluar]'):
            assert 'rincian_perintah=1' in row['data-detail-keluar'];assert row.select_one('a')['href']==row['data-detail-keluar']
        target=f'/barang-keluar/{record}?rincian_perintah=1&status=dimuat'
        fresh=await c.get(target,headers={'X-Pindah':'1'});assert fresh.status_code==200
        r=BeautifulSoup(fresh.text,'html.parser').select_one('[data-pengiriman-native]');assert r['data-pkd-record']==str(record)
        assert bool(r.select('[data-verifikasi-pengiriman][data-inline]'))==(role=='admin')
        missing=await c.get('/barang-keluar/2147483647?rincian_perintah=1',headers={'X-Pindah':'1'});assert missing.status_code==404
        assert await _sidik(pg)==before and await _stok(pg,gudang)==stock
@pytest.mark.parametrize('url,allowed',[
 ('/barang-keluar/12?rincian_perintah=1',True),('/barang-keluar/12?status=dimuat&rincian_perintah=1&tab_detail=tiket',True),
 ('/barang-keluar/12',False),('/barang-keluar/12?rincian_perintah=1&buka=verifikasi_keluar',False),
 ('/barang-keluar/12?rincian_perintah=1&nilai=12',False),('/barang-keluar/12?rincian_perintah=1&tab_detail=asing',False),
 ('/barang-keluar/12?rincian_perintah=1&rincian_perintah=0',False),('//other.invalid/barang-keluar/12?rincian_perintah=1',False),
 ('/barang-keluar/12?rincian_perintah=1#panel-barang',False),('/barang-keluar/12/perbaikan?rincian_perintah=1',False)])
async def test_only_explicit_read_family(url,allowed):
    from app.web.pengiriman_detail_kerangka import alamat_kerangka
    assert alamat_kerangka(url) is allowed
