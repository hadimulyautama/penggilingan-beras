"""Satu tab baca, tanpa perubahan penerimaan atau akses."""
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

async def test_neutral_then_native_permission_scope(pg,banyak,monkeypatch):
 clients={r:await _klien(pg,role=r) for r in ('admin','operator')};space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True);before=await _sidik(pg)
 try:
  source=await clients['admin'].get('/jasa',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'});assert source.status_code==200;s=BeautifulSoup(source.text,'html.parser');host=s.select_one('#padi-jpr-kerangka');assert host;data=json.loads(host.string);shell=BeautifulSoup(data['html'],'html.parser');root=shell.select_one('[data-jpr-shell]');assert root
  assert root.select_one('h1').text=='Penerimaan pelanggan' and root.select_one('section h2').text=='Penerimaan'
  assert not any(x in data['html'] for x in ('Bu Sri','GB-BANYAK-','JAS-BANYAK-'))
  assert len(root.select('.jasa-detail-tab a'))==5 and not root.select('.jasa-detail-tab a[href]')
  assert not root.select_one('[data-jpr-open]').has_attr('href')
  assert all(n.has_attr('disabled') for n in root.select('[data-js-cetak]'))
  assert root.select_one('[name=rincian_cari]') and not root.select_one('[name=rincian_cari]').has_attr('disabled')
  assert not shell.select('script[src*=jasa-kontrol]')
  path='/jasa/pelanggan/'+str(banyak['pelanggan_id'])
  for q in ['?tab=penerimaan','?tab=penerimaan&rincian_halaman=2','?tab=penerimaan&rincian_cari=GB-BANYAK-000','?tab=proses','?tab=ringkasan']:
   r=await clients['admin'].get(path+q,headers={'X-Pindah':'1','X-Jasa-Penerimaan-Data':'1'});assert r.status_code==200
   native=BeautifulSoup(r.text,'html.parser');assert not native.select('[data-jpr-shell]')
   if q=='?tab=penerimaan':assert len(native.select('article.jasa-catatan'))==25
  assert (await clients['operator'].get(path+'?tab=penerimaan')).status_code==403
  assert (await clients['admin'].get('/jasa/pelanggan/2147483647?tab=penerimaan')).status_code==404
  assert await _sidik(pg)==before
 finally:
  for c in clients.values():await c.aclose()

@pytest.mark.parametrize('raw,ok',[
 ('/jasa/pelanggan/1?tab=penerimaan',True),('/jasa/pelanggan/1?tab=penerimaan&status=berjalan&cari=asal&halaman=2&pesanan_halaman=3',True),
 ('/jasa/pelanggan/1?tab=penerimaan&rincian_cari=GB&rincian_halaman=2',True),('/jasa/pelanggan/1?tab=proses',False),
 ('/jasa/pelanggan/1',False),('/jasa/pelanggan/1?tab=penerimaan&pesanan_id=9',False),('/jasa/pelanggan/1?tab=penerimaan&buka=tutup_jasa',False),
 ('/jasa/pelanggan/1?tab=penerimaan#x',False),('/jasa/pelanggan/1?tab=penerimaan&tab=penerimaan',False),
 ('/jasa/pelanggan/2147483648?tab=penerimaan',False),('//other.invalid/jasa/pelanggan/1?tab=penerimaan',False)])
async def test_read_tab_only(raw,ok):
 from app.web.jasa_penerimaan_kerangka import alamat_kerangka
 assert alamat_kerangka(raw) is ok
