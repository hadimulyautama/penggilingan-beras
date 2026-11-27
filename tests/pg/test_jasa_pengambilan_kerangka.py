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
  host=BeautifulSoup(res.text,'html.parser').select_one('#padi-jgr-kerangka');assert host;data=json.loads(host.string);s=BeautifulSoup(data['html'],'html.parser');root=s.select_one('[data-jgr-shell]');assert root.select_one('h1').text=='Pengambilan & retur pelanggan'
  assert not any(x in data['html'] for x in ('Bu Sri','LOT-BANYAK','JAS-BANYAK'))
  assert len(root.select('.jasa-detail-tab a'))==5 and not root.select('.jasa-detail-tab a[href]')
  assert len(root.select('[data-jgr-target]'))==2 and not root.select('[data-jgr-target][href]')
  assert root.select_one('[data-jgr-panel] h2').text=='Pengambilan & pengiriman' and root.select_one('[data-jgr-panel] h3').text=='Retur terkait'
  assert not root.select('form') and all(x.has_attr('disabled') for x in root.select('[data-js-cetak]'))
  path='/jasa/pelanggan/'+str(banyak['pelanggan_id'])
  for q in ['?tab=pengambilan','?tab=pengambilan&status=berjalan&cari=Bu+Sri&halaman=2&pesanan_halaman=3','?tab=proses','?tab=penerimaan']:
   r=await clients['admin'].get(path+q,headers={'X-Pindah':'1','X-Jasa-Stok-Data':'1'});assert r.status_code==200
   n=BeautifulSoup(r.text,'html.parser');assert not n.select('[data-jgr-shell]')
   if q=='?tab=pengambilan':assert len(n.select('.jasa-detail > section.kartu > details'))==0 and 'Belum ada penerimaan retur terkait.' in n.text
  assert (await clients['operator'].get(path+'?tab=pengambilan')).status_code==403
  assert (await clients['admin'].get('/jasa/pelanggan/2147483647?tab=pengambilan')).status_code==404
  assert await _sidik(pg)==before
 finally:
  for c in clients.values():await c.aclose()
@pytest.mark.parametrize('raw,ok',[
 ('/jasa/pelanggan/1?tab=pengambilan',True),('/jasa/pelanggan/1?tab=pengambilan&status=berjalan&cari=asal&halaman=2&pesanan_halaman=3',True),
 ('/jasa/pelanggan/1?tab=pengambilan&rincian_cari=x',False),('/jasa/pelanggan/1?tab=proses',False),('/jasa/pelanggan/1',False),
 ('/jasa/pelanggan/1?tab=pengambilan&buka=edit',False),('/jasa/pelanggan/1?tab=pengambilan&pesanan_id=9',False),('/jasa/pelanggan/1?tab=pengambilan#x',False),
 ('/jasa/pelanggan/1?tab=pengambilan&tab=pengambilan',False),('/jasa/pelanggan/2147483648?tab=pengambilan',False),('//other.invalid/jasa/pelanggan/1?tab=pengambilan',False)])
async def test_read_tab_only(raw,ok):
 from app.web.jasa_pengambilan_kerangka import alamat_kerangka
 assert alamat_kerangka(raw) is ok
