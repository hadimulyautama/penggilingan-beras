"""Ringkasan netral tidak membaca/mencetak identitas atau saldo pelanggan."""
import json
from bs4 import BeautifulSoup
import pytest
from tests.pg.test_jasa_ringkasan_banyak import banyak
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio

async def test_neutral_then_native_scope(pg,banyak,monkeypatch):
    clients={r:await _klien(pg,role=r) for r in ('admin','operator')}
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    before=await _sidik(pg)
    try:
        c=clients['admin'];source=await c.get('/jasa',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert source.status_code==200;host=BeautifulSoup(source.text,'html.parser').select_one('#padi-jd-kerangka');assert host
        data=json.loads(host.string);s=BeautifulSoup(data['html'],'html.parser');root=s.select_one('[data-jd-shell]');assert root
        assert root.select_one('h1').text=='Ringkasan pelanggan'
        assert not any(v in data['html'] for v in ['Bu Sri','JAS-BANYAK-','GB-BANYAK-'])
        assert len(root.select('.jasa-detail-tab a'))==5 and not root.select('.jasa-detail-tab a[href]')
        assert all(n.has_attr('disabled') for n in root.select('form input:not([type=hidden]),form select,form button,[data-js-cetak]'))
        assert not s.select('script[src*=jasa-pesanan-bertahap]') and not s.select('script[src*=jasa-kontrol]')
        assert 'root.padiIsiRingkasan' in data['html']
        for q in ['', '?tab=ringkasan&pesanan_halaman=2','?tab=stok','?pesanan_id=1']:
            native=await c.get('/jasa/pelanggan/'+str(banyak['pelanggan_id'])+q,headers={'X-Pindah':'1','X-Jasa-Ringkasan-Data':'1'})
            assert native.status_code==200 and not BeautifulSoup(native.text,'html.parser').select_one('[data-jd-shell]')
        denied=await clients['operator'].get('/jasa/pelanggan/'+str(banyak['pelanggan_id']));assert denied.status_code==403
        unknown=await c.get('/jasa/pelanggan/2147483647');assert unknown.status_code==404
        assert await _sidik(pg)==before
    finally:
        for c in clients.values():await c.aclose()

@pytest.mark.parametrize('raw,ok',[
 ('/jasa/pelanggan/1',True),('/jasa/pelanggan/1?tab=ringkasan&status=berjalan&cari=asal&halaman=7',True),
 ('/jasa/pelanggan/1?pesanan_halaman=2&pesanan_cari=ORD&pesanan_status=selesai',True),
 ('/jasa/pelanggan/1?tab=stok',False),('/jasa/pelanggan/1?pesanan_id=9',False),
 ('/jasa/pelanggan/1?buka=tutup_jasa&nilai=9',False),('/jasa/pelanggan/1#pesanan-pelanggan',False),
 ('/jasa/pelanggan/1?pesanan_halaman=1&pesanan_halaman=2',False),('/jasa/pelanggan/2147483648',False),
 ('//other.invalid/jasa/pelanggan/1',False)])
async def test_only_initial_summary(raw,ok):
    from app.web.jasa_ringkasan_kerangka import alamat_kerangka
    assert alamat_kerangka(raw) is ok
