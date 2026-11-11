"""Penyajian riwayat giling; formulir, sumber dan server asli diuji bersama."""
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,ActivityLog,MillingProcess
from app.penggilingan.gudang1.services import milling as m
from tests.pg.test_form_hasil_penggilingan import hasil,g1,fakta
from tests.pg.test_form_selesai_penggilingan import lepas
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser
from tests.pg.formulir import cap_formulir
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_RIWAYAT_GILING')!='1',reason='Browser lokal opsional')]

@pytest.fixture
async def selesai(pg,hasil):
 u,pr,_=hasil
 from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
 async with pg() as db:
  actor=await db.get(User,u.id)
  for kode,a in [('GB-FORM-A',13.25),('GB-FORM-B',14.25)]:
   await catat_qc_gabah(db,user=actor,kode_batch=kode,kadar_air_1=a,kadar_air_2=a+1,biji_hijau='hampir_tidak_ada',densiti='sedang')
 await lepas(pg,u,pr)
 async with pg() as db:await m.finish_milling(db,user=await db.get(User,u.id),kode_proses=pr.kode_proses,berat_akhir=6000)
 return u,pr

@pytest.mark.parametrize('width',[1440,390,320])
async def test_tab_draf_koreksi_sumber_qc_pdf_dan_navigasi(pg,selesai,width):
 from playwright.async_api import expect
 u,pr=selesai;before=await fakta(pg,pr)
 out=Path(os.getenv('BUKTI_RIWAYAT_GILING','../bukti'));out.mkdir(parents=True,exist_ok=True)
 async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with browser(c,width) as page:
   await page.goto('/riwayat-giling/'+str(pr.id));await page.locator('[data-rhs-ready]').wait_for()
   assert await page.locator('[data-rhs-tab]').count()==5
   await expect(page.locator('#rhs-panel-ringkasan')).to_contain_text('10.000 kg')
   await expect(page.locator('#rhs-panel-ringkasan')).to_contain_text('6.000 kg')
   assert await page.locator('#rhs-tab-ringkasan').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   await page.locator('#rhs-tab-ringkasan').focus();await page.keyboard.press('ArrowRight')
   await expect(page.locator('#rhs-panel-bahan')).to_be_visible()
   await expect(page.locator('#rhs-panel-bahan')).to_contain_text('Silo A')
   await expect(page.locator('#rhs-panel-bahan')).to_contain_text('Silo B')
   await page.locator('.bahan-silo__buka>summary').first.click()
   await page.locator('.bahan-silo__asal>summary').first.click()
   await expect(page.locator('#rhs-panel-bahan')).to_contain_text('GB-FORM-A')
   await page.screenshot(path=str(out/f'bahan-{width}.png'),full_page=True)
   await page.locator('[data-rhs-edit]:visible').first.click();field=page.locator('[name=hasil_pk]')
   await field.fill('6200');await field.evaluate("e=>e.dataset.uji='asli'");await page.locator('[name=alasan]').fill('Penyesuaian hasil nyata')
   await page.locator('[data-rhs-tab=qc]').click()
   await expect(page.locator('#rhs-panel-qc')).to_contain_text('13,25%')
   await expect(page.locator('#rhs-panel-qc')).to_contain_text('15,25%')
   assert await page.locator('.qc-gabah-asal__batch').count()==2
   assert await page.locator('.qc-gabah-asal__nilai>div').count()==10
   await page.screenshot(path=str(out/f'qc-{width}.png'),full_page=True)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await page.locator('[data-rhs-tab=riwayat]').click();await expect(page.locator('#rhs-panel-riwayat')).to_contain_text('Informasi proses')
   await page.locator('[data-rhs-tab=hasil]').click();assert await field.input_value()=='6200';assert await field.get_attribute('data-uji')=='asli'
   await page.get_by_role('button',name='Periksa koreksi',exact=True).click()
   await expect(page.locator('[data-rhs-review]')).to_contain_text('6000.00 → 6200 kg')
   assert await fakta(pg,pr)==before
   await page.locator('[data-rhs-confirm]').click();await expect(page.locator('#rhs-panel-hasil')).to_contain_text('Koreksi hasil tersimpan')
   after=await fakta(pg,pr);assert after['stok'].produced==6200 and after['status']=='selesai' and after['sumber']==before['sumber']
   for suffix in ['/laporan','/laporan.pdf','/laporan.pdf?unduh=1']:
    r=await c.get('/riwayat-giling/'+str(pr.id)+suffix);assert r.status_code==200
    if '.pdf' in suffix:assert r.headers['content-type'].startswith('application/pdf')
   await page.locator('[data-lk-buka=rhs-panduan]:visible').click();await expect(page.locator('#rhs-panduan')).to_be_visible();await page.locator('[data-rhs-guide-close]').click()
   await expect(page.locator('.laporan-nav__tabs')).to_be_visible()

async def test_konflik_isian_dipertahankan_dan_periksa_ulang(pg,selesai):
 from playwright.async_api import expect
 u,pr=selesai
 async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
  async with browser(c,390) as page:
   await page.goto('/riwayat-giling/'+str(pr.id));await page.locator('[data-rhs-edit]:visible').first.click()
   await page.locator('[name=hasil_pk]').fill('6300');await page.locator('[name=alasan]').fill('Pemeriksaan ulang bersamaan')
   async with pg() as db:await m.koreksi_hasil_giling(db,user=await db.get(User,u.id),process_id=pr.id,hasil_kg=6100,dasar_kg=6000,alasan='Catatan lain')
   await page.get_by_role('button',name='Periksa koreksi',exact=True).click();await page.locator('[data-rhs-confirm]').click()
   await expect(page.locator('[name=periksa_ulang]')).to_be_visible()
   assert await page.locator('[name=hasil_pk]').input_value()=='6300';assert await page.locator('[name=alasan]').input_value()=='Pemeriksaan ulang bersamaan'
   await expect(page.locator('#rhs-panel-hasil')).to_contain_text('Catatan berubah')
   await page.locator('[name=periksa_ulang]').check();await page.get_by_role('button',name='Periksa koreksi',exact=True).click();await page.locator('[data-rhs-confirm]').click()
   await expect(page.locator('#rhs-panel-hasil')).to_contain_text('Koreksi hasil tersimpan')
   assert (await fakta(pg,pr))['stok'].produced==6300

async def test_operator_dan_koreksi_tertahan_setelah_transfer(pg,selesai):
 from playwright.async_api import expect
 from app.services.transfer import create_internal_transfer
 u,pr=selesai
 async with pg() as db:await create_internal_transfer(db,user=await db.get(User,u.id),kode_proses=pr.kode_proses,lokasi_tujuan='ditumpuk',berat=2000)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  async with browser(c,390) as page:
   await page.goto('/riwayat-giling/'+str(pr.id)+'?tab_detail=hasil')
   assert await page.locator('[data-rhs-edit],.riwayat-koreksi__form').count()==0
   await expect(page.locator('#rhs-panel-hasil')).to_contain_text('4.000 kg')
   await page.locator('[data-rhs-tab=qc]').click();await expect(page.locator('#rhs-panel-qc')).to_contain_text('13,25%')
 async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
  async with browser(c,1440) as page:
   await page.goto('/riwayat-giling/'+str(pr.id));await page.locator('[data-rhs-edit]:visible').first.click()
   assert await page.locator('.riwayat-koreksi__form').count()==0
   await expect(page.locator('[data-rhs-correction]')).to_contain_text('transfer')
   assert await page.locator('[data-rhs-correction] a').count()>0

async def test_belum_dicatat_riwayat_jeda_dan_fallback_tab(pg,hasil):
 from playwright.async_api import expect
 from app.penggilingan.gudang1.services import jeda as j
 u,pr,_=hasil
 async with pg() as db:
  actor=await db.get(User,u.id)
  await j.hentikan(db,user=actor,jenis='giling',kode=pr.kode_proses,sebab='Listrik padam')
  await j.lanjutkan(db,user=actor,jenis='giling',kode=pr.kode_proses)
 await lepas(pg,u,pr)
 async with pg() as db:
  actor=await db.get(User,u.id)
  await m.finish_milling(db,user=actor,kode_proses=pr.kode_proses,berat_akhir=6000)
  await m.koreksi_hasil_giling(db,user=actor,process_id=pr.id,hasil_kg=0,dasar_kg=6000,alasan='Uji kondisi hasil belum diketahui sesuai reader asli')
 async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
  async with browser(c,320) as page:
   await page.goto('/riwayat-giling/'+str(pr.id))
   await expect(page.locator('#rhs-panel-ringkasan')).to_contain_text('Belum dicatat')
   assert await page.locator('.rhs-mass strong').nth(2).inner_text()=='—'
   await page.goto('/riwayat-giling/'+str(pr.id)+'#riwayat-jeda')
   await expect(page.locator('#rhs-panel-riwayat')).to_be_visible()
   await expect(page.locator('#riwayat-jeda')).to_contain_text('Listrik padam')
   await expect(page.locator('#riwayat-jeda')).to_contain_text('Waktu kejadian')
   await expect(page.locator('#riwayat-jeda')).to_contain_text('Dicatat pada')
   for tab in ['bahan','hasil','qc','riwayat']:
    r=await c.get('/riwayat-giling/'+str(pr.id)+'?tab_detail='+tab)
    assert r.status_code==200
    from bs4 import BeautifulSoup
    html=BeautifulSoup(r.text,'html.parser');assert 'hidden' not in html.select_one('#rhs-panel-'+tab).attrs
