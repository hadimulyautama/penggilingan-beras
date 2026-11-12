"""Kontrol baru tetap mengantar ke pembaca, izin, dan isi lama."""
import os
from pathlib import Path
import pytest
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_riwayat_giling import _klien
pytestmark=pytest.mark.asyncio

async def test_kontrol_bersama_dan_seluruh_pilihan_tetap(pg,qc,tmp_path):
 out=Path(os.environ.get('BUKTI_LAPORAN_KONTROL',str(tmp_path)));out.mkdir(parents=True,exist_ok=True)
 async with await _klien(pg,peran='superadmin') as c:
  routes={'laporan':'/laporan','proses':'/riwayat-pengeringan','qc':'/riwayat-qc/gabah-basah','audit':'/audit?rentang=semua&kelompok=giling&cari=LOT','detail':'/riwayat-qc/gabah-kering/GB-QC-KERING'}
  for name,url in routes.items():
   r=await c.get(url);assert r.status_code==200
   assert 'data-laporan-kontrol' in r.text and 'class="pd-panduan"' in r.text
   from bs4 import BeautifulSoup
   nav=BeautifulSoup(r.text,'html.parser').select('[data-laporan-kontrol][aria-label]')
   assert len(nav)==1 and nav[0]['aria-label']
   from hmu_tampilan import CAP_ASET
   assert f'laporan-kontrol.js?v={CAP_ASET}' in r.text
   (out/(name+'.html')).write_text(r.text)
  html=(out/'laporan.html').read_text()
  from app.services.laporan_periode import TAHAP
  from app.web.laporan import PERIODE
  soup=BeautifulSoup(html,'html.parser')
  links=soup.select('[data-laporan]')
  assert {a['data-laporan'] for a in links} == {'tahap_'+k for k in TAHAP}
  assert all(a.get('data-berperiode')=='1' for a in links)
  for a in links:
   detail=await c.get(a['href']);assert detail.status_code==200
   screen=BeautifulSoup(detail.text,'html.parser')
   assert screen.select_one('#periode') is not None
   assert {o['value'] for o in screen.select('#periode option')} == {k for k,_ in PERIODE}
  html=(out/'audit.html').read_text()
  assert 'value="semua" selected' in html and 'value="giling" selected' in html and 'value="LOT"' in html
  assert 'id="lk-filter"' in html and 'name="cari"' in html
  assert 'QC 5' in (out/'detail.html').read_text()
