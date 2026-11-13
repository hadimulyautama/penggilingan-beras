from pathlib import Path
import os
from types import SimpleNamespace as N
from urllib.parse import urlsplit,parse_qs
import pytest
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader
from starlette.requests import Request
from playwright.sync_api import sync_playwright,expect
from app.services.jasa_bahan import ringkas
from app.services.bahan_silo import kg_rinci
R=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('width',[320,390,1440])
def test_kontrol_kartu_bahan_dan_tautan_tetap(width,tmp_path):
 e=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}'}),FileSystemLoader(R/'hmu_tampilan/templates')]),autoescape=True);calls=[]
 def render(url):
  u=urlsplit(url);q={k:v[0] for k,v in parse_qs(u.query,keep_blank_values=True).items()};calls.append(q)
  request=Request(dict(type='http',path='/jasa',query_string=u.query.encode(),headers=[],scheme='http',server=('uji.local',80)))
  def customer(id,name):
   return N(id=id,nama=name,penerimaan_jumlah=3,pesanan_jumlah=2,penerimaan=[],pesanan=[],pekerjaan=1,berjalan=1,
    pk_kg=0,beras_kg=0,samping_kg=0,stok=[],kondisi=['Bahan masih di pabrik'],bahan_titipan=ringkas(([
     dict(jenis_bahan='Gabah',tahap_bahan='pengering',label_bahan='Gabah di pengering',kg=21337,final=True,sumber_bahan='d1'),
     dict(jenis_bahan='Gabah',tahap_bahan='silo_giling',label_bahan='Gabah di silo / proses giling',kg=32843.5,final=False,sumber_bahan='s1')]+([dict(jenis_bahan='PK',tahap_bahan='penempatan',label_bahan='PK menunggu penempatan',kg=None,final=False,sumber_bahan='pk1')] if id==314 else []))))
  html=e.get_template('jasa_pelanggan.html').render(request=request,VERSI='518',cari=q.get('cari',''),tapis=q.get('status',''),STATUS_PILIHAN=[('','Semua pesanan'),('berjalan','Berjalan')],jumlah=2,kartu=[customer(313,'Pak Suroto'),customer(314,'Pelanggan kedua')],kg=kg_rinci,halaman=1,akhir=2)
  css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','panduan.css','kontrol-halaman.css'])
  return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui terik"><style>body{padding-left:0!important}</style><main class="isi">'+html+'</main><script>window.print=()=>window.cetak=(window.cetak||0)+1</script></body>'
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1000));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlsplit(r.request.url).path
   if path=='/jasa':r.fulfill(body=render(r.request.url),content_type='text/html');return
   f=R/'hmu_tampilan'/path.lstrip('/')
   if f.is_file():r.fulfill(path=f)
   else:r.fulfill(body='')
  page.route('**/*',route);page.goto('http://uji.local/jasa?halaman=2')
  assert page.locator('a.jasa-pelanggan').count()==2
  assert '21.337 kg' in page.locator('a.jasa-pelanggan').first.inner_text()
  assert '32.843,5 kg' in page.locator('a.jasa-pelanggan').first.inner_text()
  if width==1440:

   for selector in ['.jasa-pelanggan h2','.jasa-pelanggan .jasa-angka','.jasa-pelanggan .jasa-buka']:
    yy=[v.bounding_box()['y'] for v in page.locator(selector).all()];assert max(yy)-min(yy)<1,(selector,yy)
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.get_by_role('searchbox').fill('Suroto');page.get_by_role('button',name='Cari',exact=True).click();page.wait_for_url('**cari=Suroto**');assert 'halaman' not in calls[-1]
  page.locator('.kontrol-filter').click();page.locator('#js-filter [name=status]').select_option('berjalan');page.get_by_role('button',name='Terapkan filter').click();page.wait_for_url('**status=berjalan**');assert calls[-1]['cari']=='Suroto'
  assert 'status=berjalan' in page.locator('a.jasa-pelanggan').first.get_attribute('href')
  page.locator('.kontrol-aksi [data-js-buka="js-panduan"]').click()
  expect(page.locator('#js-panduan')).to_be_visible();assert 'Pos Timbang' in page.locator('#js-panduan').inner_text();page.keyboard.press('Escape')
  page.locator('.kontrol-aksi [data-js-cetak]').click()
  assert page.evaluate('window.cetak')==1;assert not errors,errors
  out=Path(os.environ.get('BUKTI_JASA_KONTROL',str(tmp_path)));out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/f'daftar-{width}.png'),full_page=True);b.close()
