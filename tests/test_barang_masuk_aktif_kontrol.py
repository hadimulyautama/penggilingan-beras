from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader
from starlette.requests import Request
from playwright.sync_api import sync_playwright,expect
import pytest
R=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('status',['belum','diterima'])
def test_halaman_aktif_dan_pencarian_server(width,status,tmp_path):
 env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'<div class="bingkai"><main class="isi">{% block isi %}{% endblock %}</main></div>'}),FileSystemLoader(R/'app/web/templates'),FileSystemLoader(R/'hmu_tampilan/templates')]),autoescape=True)
 env.filters['jam']=lambda *_:'04/11/2026';calls=[]
 def render(url):
  u=urlsplit(url);q={k:v[0] for k,v in parse_qs(u.query,keep_blank_values=True).items()};calls.append(q)
  req=Request(dict(type='http',path='/barang-masuk',query_string=u.query.encode(),headers=[],scheme='http',server=('uji.local',80)))
  html=env.get_template('barang_masuk_pencarian.html').render(request=req,VERSI='501',TAMPILAN_INDUK=True,VIEW='super',V_MEJA=['super'],status=q.get('status',status),jenis=q.get('jenis',''),pemilik=q.get('kepemilikan',''),gudang=q.get('gudang',''),cari=q.get('cari',''),pemasok=q.get('pemasok',''),total_belum=0,total_diterima=0,jumlah=0,menunggu=[],riwayat=[],gagal=False,pelanggan_saring='',nama_saring=['Pak Suroto'],jenis_barang=[('gabah','Gabah'),('pk','PK')],halaman_akhir=1,href=lambda **p:'/barang-masuk?'+urlencode(dict(q,**p)))
  css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','panduan.css','kontrol-halaman.css'])
  return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui terik">'+html+'<script src="/static/barang-masuk.js?v=501"></script><script src="/static/barang-masuk-pencarian.js?v=501"></script></body>'
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=844));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlsplit(r.request.url).path
   if path=='/barang-masuk':r.fulfill(body=render(r.request.url),content_type='text/html')
   else:
    f=next((f for f in [R/'app/web'/path.lstrip('/'),R/'hmu_tampilan'/path.lstrip('/')] if f.is_file()),None)
    if f:r.fulfill(path=f)
    else:r.fulfill(body='')
  page.route('**/*',route);page.goto('http://uji.local/barang-masuk?status='+status)
  page.get_by_role('searchbox').fill('Suroto');assert len(calls)==1
  expect(page.locator('#bm-belum-cari')).to_be_visible();page.get_by_role('button',name='Cari',exact=True).click()
  expect(page.locator('.bm-jumlah')).to_contain_text('Suroto');assert calls[-1]['cari']=='Suroto'
  trigger=page.locator('.bm-tindakan-ponsel [data-bm-buka="bm-filter"]' if width==390 else '.kontrol-filter')
  trigger.click();expect(page.locator('#bm-filter')).to_be_visible();page.locator('#bm-filter [name=jenis]').select_option('pk')
  page.get_by_role('button',name='Terapkan filter').click();page.wait_for_url('**/barang-masuk?**jenis=pk**');assert calls[-1]['cari']=='Suroto'
  trigger.click();page.keyboard.press('Escape');expect(page.locator('#bm-filter')).not_to_be_visible()
  if width==390:
   page.get_by_role('button',name='Panduan dan print',exact=True).click();page.get_by_role('button',name='Panduan penerimaan',exact=True).click()
  else:page.locator('.bm-tindakan-desktop [data-bm-buka]').click()
  expect(page.locator('#bm-panduan')).to_be_visible();page.get_by_role('button',name='Tutup panduan').click()
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  out=tmp_path/'potret';out.mkdir();page.screenshot(path=str(out/f'{status}-{width}.png'),full_page=True)
  assert not errors;b.close()
@pytest.mark.asyncio
async def test_rute_internal_memakai_pembaca_pencarian(monkeypatch):
 from app.web import layar_pekerjaan,barang_masuk_pencarian
 monkeypatch.setattr(layar_pekerjaan,'tautan_penerimaan_lama',lambda _:None);monkeypatch.setattr(layar_pekerjaan,'is_customer_read',lambda _:False)
 async def halaman(request,akun):return 'pencarian-aktif'
 monkeypatch.setattr(barang_masuk_pencarian,'halaman',halaman)
 assert await layar_pekerjaan.halaman_barang_masuk(object(),object())=='pencarian-aktif'
