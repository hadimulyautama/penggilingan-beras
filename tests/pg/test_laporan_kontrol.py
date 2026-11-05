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
   assert r.text.count('aria-label="Bagian Laporan dan Riwayat"')==1
   assert 'laporan-kontrol.js?v=523' in r.text
   (out/(name+'.html')).write_text(r.text)
  html=(out/'laporan.html').read_text()
  assert html.count('data-laporan="')==7
  assert html.count('data-berperiode="1"')==2
  assert 'href="/serah-terima"' in html and 'id="periode"' in html
  assert html.count('<option value=')==6
  html=(out/'audit.html').read_text()
  assert 'value="semua" selected' in html and 'value="giling" selected' in html and 'value="LOT"' in html
  assert 'id="lk-filter"' in html and 'name="cari"' in html
  assert 'QC 5' in (out/'detail.html').read_text()
