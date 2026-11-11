"""Navigasi dan panduan konsisten antar-tab, seluruh data retur tetap dibaca."""
from pathlib import Path
from types import SimpleNamespace as N
from urllib.parse import urlsplit
import pytest
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader
from starlette.requests import Request
from playwright.sync_api import sync_playwright,expect
R=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('light',[True,False])
def test_dua_tab_satu_kerangka_dan_informasi_retur_utuh(width,light,tmp_path):
 env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}{% block kaki %}{% endblock %}'}),FileSystemLoader([R/'app/web/templates',R/'hmu_tampilan/templates'])]),autoescape=True)
 env.filters['jam']=lambda *a:'05/11/2026'
 def render(path):
  req=Request(dict(type='http',path=path,query_string=b'',headers=[],scheme='http',server=('uji.local',80)))
  if path=='/retur':
   html=env.get_template('retur_daftar.html').render(request=req,VERSI='515',BOLEH_PERINTAH=True,pesan='Pemeriksaan disimpan',gagal='Tiket perlu diperiksa',
    pengajuan=[N(id=8,kode_pengiriman='OUT-UJI-88',nama_pembeli='Pak Suroto',kode_tiket='TT-UJI-12',status_pemeriksaan='menunggu_timbang')],
    pengajuan_berikut=7,lama=[N(kode_tiket='TIKET-LAMA-19')],
    recent=[N(id=22,kode='RET-UJI-22',nama_pelanggan='CV Makmur',nomor_polisi='AD 1234 ZX',kode_tiket='TT-UJI-10',waktu=None,berat_rincian_kg=250,jumlah_jenis=2,selisih_kg=5)],sebelum_berikut=21)
  else:
   html=env.get_template('_barang_keluar_kontrol.html').render(request=req,VERSI='515',BOLEH_PERINTAH=True,pencarian='',status_filter='',sejak_filter='',n_perintah=2,n_dimuat=1)
  css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','panduan.css'])
  return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui '+('terik' if light else '')+'"><style>body{padding-left:0!important}</style><main class="isi">'+html+'</main><script>window.print=()=>window.cetak=(window.cetak||0)+1</script></body>'
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1000));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlsplit(r.request.url).path
   if path in ['/retur','/barang-keluar']:r.fulfill(body=render(path),content_type='text/html');return
   f=next((f for f in [R/'app/web'/path.lstrip('/'),R/'hmu_tampilan'/path.lstrip('/')] if f.is_file()),None)
   if f:r.fulfill(path=f)
   else:r.fulfill(body='')
  page.route('**/*',route);styles=[]
  for path in ['/barang-keluar','/retur']:
   page.goto('http://uji.local'+path)
   assert page.locator('.pengiriman-kontrol').count()==1
   assert page.locator('.pengiriman-kontrol .pengiriman-tab a').count()==2
   assert page.locator('.pengiriman-kontrol .pengiriman-tab a[aria-current]').get_attribute('href')==path
   tab=page.locator('.pengiriman-tab a[aria-current]');styles.append(tab.evaluate('(e)=>{const s=getComputedStyle(e);return [s.fontSize,s.padding,s.borderBottomWidth,s.borderBottomColor,s.backgroundColor]}'))
   if path=='/retur':
    assert page.get_by_role('searchbox').count()==0
    assert page.get_by_role('link',name='Buka riwayat pengiriman').count()==0
    assert page.locator('[data-bk-buka="bk-filter"]').count()==0
    for text in ['OUT-UJI-88','Pak Suroto','TT-UJI-12','TIKET-LAMA-19','RET-UJI-22','CV Makmur','AD 1234 ZX','TT-UJI-10','250','5','2 jenis barang','Belum masuk stok','Pemeriksaan disimpan','Tiket perlu diperiksa']:
     assert text in page.locator('main').inner_text(),text
    for href in ['/retur/pengajuan/8','/retur/22','/retur?sebelum_pengajuan=7','/retur?sebelum=21']:
     assert page.locator('a[href="'+href+'"]').count()==1,href
   page.locator('.bk-desktop[data-bk-buka="bk-panduan"]').click()
   guide=page.locator('#bk-panduan');expect(guide).to_be_visible();assert guide.get_attribute('class')=='pd-panduan'
   if path=='/retur':assert 'Buka pengiriman yang sudah keluar → ajukan retur → timbang dan periksa barang → terima ke stok.' in guide.inner_text()
   bounds=guide.bounding_box();assert bounds['width']<=width and bounds['x']>=0
   page.keyboard.press('Escape');expect(guide).not_to_be_visible()
   page.locator('.bk-desktop[data-bk-cetak]').click()
   assert page.evaluate('window.cetak')==1
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.screenshot(path=str(tmp_path/(path[1:]+'.png')),full_page=True)
  assert styles[0]==styles[1],styles
  assert not errors,errors
  b.close()
