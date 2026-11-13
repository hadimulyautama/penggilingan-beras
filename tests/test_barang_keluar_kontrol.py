"""Kontrol asli: izin dropdown, parameter pencarian, panduan dan cetak."""
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from jinja2 import Environment,FileSystemLoader
from starlette.requests import Request
from playwright.sync_api import sync_playwright,expect
R=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('admin',[False,True])
def test_kontrol_pengiriman_dan_panduan_bersama(width,admin):
 env=Environment(loader=FileSystemLoader([R/'app/web/templates',R/'hmu_tampilan/templates']),autoescape=True);calls=[]
 def document(url):
  u=urlsplit(url);q={k:v[0] for k,v in parse_qs(u.query,keep_blank_values=True).items()};calls.append(q)
  request=Request(dict(type='http',path='/barang-keluar',query_string=u.query.encode(),headers=[],scheme='http',server=('uji.local',80)))
  html=env.get_template('_barang_keluar_kontrol.html').render(request=request,VERSI='514',BOLEH_PERINTAH=admin,tab_pengiriman='keluar',pencarian=q.get('q',''),status_filter=q.get('status',''),sejak_filter=q.get('sejak',''),n_perintah=2,n_dimuat=1)
  css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','panduan.css','kontrol-halaman.css'])+(R/'hmu_tampilan/static/pengiriman-kontrol.css').read_text()
  return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui terik"><style>body{padding-left:0!important}</style><main class="isi"><div class="keluar-ringkas">'+html+'</div></main><script>window.print=()=>window.cetakan=(window.cetakan||0)+1</script><script src="/static/bantuan_pengiriman.js"></script><script src="/static/pengiriman-kontrol.js"></script></body>'
 with sync_playwright() as p:
  browser=p.chromium.launch();page=browser.new_page(viewport=dict(width=width,height=900));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlsplit(r.request.url).path
   if path=='/barang-keluar':r.fulfill(body=document(r.request.url),content_type='text/html')
   else:
    f=next((f for f in [R/'app/web'/path.lstrip('/'),R/'hmu_tampilan'/path.lstrip('/')] if f.is_file()),R/'tidak-ada')
    if f.is_file():r.fulfill(path=f)
    else:r.fulfill(body='')
  page.route('**/*',route);page.goto('http://uji.local/barang-keluar?pelanggan_id=7&sebelum=51')
  assert page.locator('[data-bk-buat]').count()==int(admin)
  if admin:
   assert page.locator('[data-bk-buat] summary').evaluate('(e)=>getComputedStyle(e).backgroundColor')!=page.locator('.kontrol-tombol[data-bk-buka="bk-panduan"]').evaluate('(e)=>getComputedStyle(e).backgroundColor')
   page.locator('[data-bk-buat] summary').click()
   for url in ['/barang-keluar/baru','/barang-keluar/pengambilan-jasa']:expect(page.locator('[data-bk-buat] a[href="'+url+'"]')).to_be_visible()
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.keyboard.press('Escape');assert not page.locator('[data-bk-buat]').evaluate('(e)=>e.open')
  if width==1440:
   boxes=[page.locator(s).bounding_box() for s in ['.kontrol-filter','.kontrol-pencarian__form input[type=search]','.kontrol-pencarian__form>button']]
   assert max(b['y'] for b in boxes)-min(b['y'] for b in boxes)<2
  page.get_by_role('searchbox').fill('Suroto');page.get_by_role('button',name='Cari',exact=True).click();page.wait_for_url('**q=Suroto**')
  assert calls[-1]['pelanggan_id']=='7' and 'sebelum' not in calls[-1]
  page.get_by_role('searchbox').fill('belum dikirim')
  page.locator('.kontrol-filter').click()
  page.locator('#bk-filter [name=status]').select_option('dimuat');page.locator('#bk-filter [name=sejak]').fill('2026-11-01')
  page.get_by_role('button',name='Terapkan filter').click();page.wait_for_url('**status=dimuat**')
  assert calls[-1]['q']=='belum dikirim' and calls[-1]['sejak']=='2026-11-01' and calls[-1]['pelanggan_id']=='7'
  page.locator('.kontrol-tombol[data-bk-buka="bk-panduan"]').click()
  dialog=page.locator('dialog.pd-panduan');expect(dialog).to_be_visible()
  page.locator('#panduan-tahap-3').click();expect(page.locator('#panduan-panel-3')).to_be_visible()
  assert 'stok tidak dikurangi untuk kedua kalinya' in page.locator('#panduan-panel-3').inner_text().lower()
  bounds=dialog.bounding_box();assert bounds['width']<=width and bounds['x']>=0
  assert bounds['height']<810
  assert page.locator('#panduan-tahap-3').evaluate('(e)=>getComputedStyle(e).backgroundColor')!=page.locator('#panduan-tahap-1').evaluate('(e)=>getComputedStyle(e).backgroundColor')
  assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth')
  page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
  page.locator('.kontrol-tombol[data-bk-cetak]').click()
  assert page.evaluate('window.cetakan')==1
  assert not errors,errors
  browser.close()
