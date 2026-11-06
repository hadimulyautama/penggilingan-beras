"""Indikator portal memakai visual produksi, dengan makna dan angka yang sama."""
from pathlib import Path
from types import SimpleNamespace as NS
from copy import deepcopy
import pytest
from bs4 import BeautifulSoup
from app.web.tampilan import templates
from app.web.portal.proses_ringkas import indikator_hasil
from app.penggilingan.gudang2.polishing import neraca_sosoh


def kartu(jenis,rend=None,neraca=None):
 return dict(jenis=jenis,maju=None,indikator_hasil=indikator_hasil(NS(rendemen_sementara=rend,neraca=neraca),jenis))


def render(r):
 return templates.env.get_template('portal/_bobot_proses.html').module.kemajuan(r,'uji-progres')

@pytest.mark.parametrize('rend',[None,0,65,110])
def test_hasil_giling_tidak_diubah_menjadi_persen_selesai(rend):
 r=kartu('giling',rend);before=deepcopy(r)
 s=BeautifulSoup(render(r),'html.parser')
 assert 'Rendemen sementara' in s.get_text() and 'bukan persentase proses selesai' in s.get_text()
 bar=s.select_one('progress')
 assert bool(bar)==(rend is not None and 0<=rend<=100)
 if bar:assert float(bar['value'])==rend and float(bar['max'])==100
 if rend==110:assert 'Hasil melebihi bahan' in s.get_text()
 assert r==before

@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('jenis',['giling','sosoh'])
def test_bar_terlihat_di_ponsel_dan_desktop(width,jenis,tmp_path):
 from playwright.sync_api import sync_playwright
 root=Path(__file__).resolve().parents[1]
 neraca=neraca_sosoh(10000,{'medium':6500,'broken':1200,'menir':700,'bekatul':1500})
 content=render(kartu(jenis,65,neraca if jenis=='sosoh' else None))
 css=''.join((root/p).read_text() for p in ['hmu_tampilan/static/app.css','hmu_tampilan/static/komponen-portal.css','app/web/static/portal-pelanggan.css'])
 with sync_playwright() as pw:
  browser=pw.chromium.launch();page=browser.new_page(viewport={'width':width,'height':850})
  page.set_content('<style>'+css+'</style><body class="portal-customer terik"><main class="pelanggan-halaman"><article class="pelanggan-proses-kartu">'+str(content)+'</article></main></body>')
  bar=page.locator('progress' if jenis=='giling' else '.neraca')
  assert bar.is_visible() and bar.bounding_box()['width']>200 and bar.bounding_box()['height']>=9
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  if jenis=='sosoh':
   assert 'beras 65,0%' in bar.get_attribute('aria-label')
   parts=page.locator('.neraca>span').evaluate_all('(els)=>els.map(e=>e.getBoundingClientRect().width)')
   assert parts[0]>parts[1]>parts[2]>0
  out=tmp_path/'portal-progress-visual';out.mkdir(exist_ok=True)
  page.screenshot(path=str(out/f'{jenis}-{width}.png'),full_page=True)
  browser.close()
