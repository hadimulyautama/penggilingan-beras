"""Native saldo remains authoritative; the destination shell never creates stock."""
import json
import pytest
from bs4 import BeautifulSoup
from tests.pg.test_jasa_ringkasan_banyak import banyak
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
pytestmark=pytest.mark.asyncio
async def test_neutral_then_native_scope(pg,banyak,monkeypatch):
 clients={r:await _klien(pg,role=r) for r in ('admin','operator')};space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True);before=await _sidik(pg)
 try:
  res=await clients['admin'].get('/jasa',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert res.status_code==200
  host=BeautifulSoup(res.text,'html.parser').select_one('#padi-jst-kerangka');assert host;data=json.loads(host.string);s=BeautifulSoup(data['html'],'html.parser');root=s.select_one('[data-jst-shell]');assert root.select_one('h1').text=='Stok pelanggan'
  assert not any(x in data['html'] for x in ('Bu Sri','LOT-BANYAK','JAS-BANYAK'))
  assert len(root.select('.jasa-detail-tab a'))==5 and not root.select('.jasa-detail-tab a[href]')
  assert len(root.select('[data-jst-target]'))==3 and not root.select('[data-jst-target][href]')
  assert [x.text for x in root.select('.jasa-stok__kepala span')]==['Barang / sumber','Lokasi','Saldo']
  assert not root.select('form') and all(x.has_attr('disabled') for x in root.select('[data-js-cetak]'))
  path='/jasa/pelanggan/'+str(banyak['pelanggan_id'])
  for q in ['?tab=stok','?tab=stok&status=berjalan&cari=Bu+Sri&halaman=2&pesanan_halaman=3','?tab=proses','?tab=penerimaan']:
   r=await clients['admin'].get(path+q,headers={'X-Pindah':'1','X-Jasa-Stok-Data':'1'});assert r.status_code==200
   n=BeautifulSoup(r.text,'html.parser');assert not n.select('[data-jst-shell]')
   if q=='?tab=stok':assert len(n.select('.jasa-stok > article'))==26
  assert (await clients['operator'].get(path+'?tab=stok')).status_code==403
  assert (await clients['admin'].get('/jasa/pelanggan/2147483647?tab=stok')).status_code==404
  assert await _sidik(pg)==before
 finally:
  for c in clients.values():await c.aclose()
@pytest.mark.parametrize('raw,ok',[
 ('/jasa/pelanggan/1?tab=stok',True),('/jasa/pelanggan/1?tab=stok&status=berjalan&cari=asal&halaman=2&pesanan_halaman=3',True),
 ('/jasa/pelanggan/1?tab=stok&rincian_cari=x',False),('/jasa/pelanggan/1?tab=proses',False),('/jasa/pelanggan/1',False),
 ('/jasa/pelanggan/1?tab=stok&buka=edit',False),('/jasa/pelanggan/1?tab=stok&pesanan_id=9',False),('/jasa/pelanggan/1?tab=stok#x',False),
 ('/jasa/pelanggan/1?tab=stok&tab=stok',False),('/jasa/pelanggan/2147483648?tab=stok',False),('//other.invalid/jasa/pelanggan/1?tab=stok',False)])
async def test_read_tab_only(raw,ok):
 from app.web.jasa_stok_kerangka import alamat_kerangka
 assert alamat_kerangka(raw) is ok
