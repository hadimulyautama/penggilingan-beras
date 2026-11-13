from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs
import subprocess
import pytest
from jinja2 import Environment,FileSystemLoader
from starlette.requests import Request
from playwright.sync_api import sync_playwright,expect
R=Path(__file__).resolve().parents[1]

def test_isi_daftar_dan_kartu_tetap_sama():
 import hashlib
 sekarang=(R/'app/web/templates/pekerjaan.html').read_text()
 sebelum,sesudah=sekarang.split("{% include '_pekerjaan_kontrol.html' %}",1)
 assert hashlib.sha256(sebelum.encode()).hexdigest()=='f328c94b5c7d839f916350e1539fa27d5eac47682d35f3eb41658efc355d186b'
 # Jumlah tindakan cukup di tab; petunjuk penerimaan dipusatkan di Panduan.
 assert hashlib.sha256(sesudah.encode()).hexdigest()=='2923e709ebcfa43d645aabe6865249b87992fcea635cf45a9a62d1f273cc13cc'
 for f,sidik in {'app/web/templates/_pekerjaan_berjalan_ringkas.html': 'b187e6dac3dcb75668bd74ce00d140c7d77acf091cf3e527f24d30b1cb487d98', 'hmu_tampilan/templates/_benda.html': '8a398c994cd66faed3daaa5153f9f20aadb7ea5f81cd9f7b7538df7dc62018a0'}.items():
  isi=(R/f).read_text()
  if f.endswith('/_benda.html'):
   # Kartu memakai transfer PK generik dan pembungkus isi responsif.
   # Snapshot juga mencakup pembungkus isi kartu transfer;
   # kartu QC tetap dinormalisasi terpisah.
   from tests.kartu_asli import tanpa_kartu_qc
   isi=tanpa_kartu_qc(isi)
  assert hashlib.sha256(isi.encode()).hexdigest()==sidik

@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('tab',['tindakan','berjalan'])
def test_kontrol_saja(width,tab,tmp_path):
 env=Environment(loader=FileSystemLoader([R/'app/web/templates',R/'hmu_tampilan/templates']),autoescape=True)
 calls=[]
 def render(url):
  u=urlsplit(url);q={k:v[0] for k,v in parse_qs(u.query,keep_blank_values=True).items()};calls.append(q)
  req=Request(dict(type='http',path='/pekerjaan',query_string=u.query.encode(),headers=[],scheme='http',server=('uji.local',80)))
  h=env.get_template('_pekerjaan_kontrol.html').render(request=req,VERSI='502',TAMPILAN_INDUK=True,VIEW='super',V_MEJA=['super'],tab=q.get('tab',tab),jenis=q.get('jenis',''),gudang=q.get('gudang',''),total_tindakan=3,total_jalan=2,nama_saring=['Pak Suroto'],pelanggan_saring='',per_jenis=[('giling','Giling',2)],href=lambda **p:'/pekerjaan?'+urlencode(dict(q,**p)))
  css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','panduan.css','kontrol-halaman.css'])
  return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui terik"><div class="bingkai"><main class="isi">'+h+'<section id="daftar-asli">Daftar pekerjaan tetap di sini.</section></main></div></body>'
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=844));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlsplit(r.request.url).path
   if path=='/pekerjaan':r.fulfill(body=render(r.request.url),content_type='text/html')
   else:
    f=R/'hmu_tampilan'/path.lstrip('/')
    if f.is_file():r.fulfill(path=f)
    else:r.fulfill(body='')
  page.route('**/*',route);page.goto('http://uji.local/pekerjaan?tab='+tab+'&pelanggan_id=7&halaman=2')
  assert page.get_by_role('navigation',name='Tab pekerjaan').locator('a').count()==3
  page.get_by_role('searchbox').fill('Suroto');assert len(calls)==1
  page.get_by_role('button',name='Cari',exact=True).click();page.wait_for_url('**cari=Suroto**')
  assert calls[-1]['pelanggan_id']=='7' and 'halaman' not in calls[-1]
  trigger=page.locator('.kontrol-filter')
  if width==1440:
   boxes=[page.locator(s).bounding_box() for s in ['.kontrol-filter','.kontrol-pencarian__form .kontrol-pencarian__field','.kontrol-pencarian__form > button']]
   assert max(x['y'] for x in boxes)-min(x['y'] for x in boxes)<2
  trigger.click();expect(page.locator('#pk-filter')).to_be_visible()
  page.locator('#pk-filter [name=jenis]').select_option('giling');page.locator('#pk-filter [name=gudang]').select_option('g2')
  page.get_by_role('button',name='Terapkan filter').click();page.wait_for_url('**jenis=giling**')
  assert calls[-1]['cari']=='Suroto' and calls[-1]['gudang']=='g2' and calls[-1]['tab']==tab
  trigger.click();page.keyboard.press('Escape');expect(page.locator('#pk-filter')).not_to_be_visible();expect(trigger).to_be_focused()
  if width!=1440:
   page.get_by_role('button',name='Panduan dan print',exact=True).click();page.get_by_role('button',name='Panduan pekerjaan',exact=True).click()
  else:page.locator('.pk-tindakan-desktop [data-pk-buka]').click()
  expect(page.locator('#pk-panduan')).to_be_visible();page.get_by_role('button',name='Tutup panduan').click()
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  out=tmp_path/'qa-pekerjaan-kontrol';out.mkdir();page.screenshot(path=str(out/f'{tab}-{width}.png'),full_page=True)
  assert not errors;b.close()
