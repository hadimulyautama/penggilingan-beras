"""Kontrol bersama mempertahankan daftar, cakupan, detail/PDF dan kursor asli."""
import os,re
from pathlib import Path
import pytest
import pytest_asyncio
from sqlalchemy import select,func
from hmu_identitas.peran import SUPERADMIN,OPERATOR
from app.models import User,Silo,Warehouse,ActivityLog
from tests.pg.test_riwayat_pengeringan import pabrik,_lot_selesai
from tests.pg.test_riwayat_giling import _giling_selesai,_klien
from tests.pg.test_riwayat_sosoh import _sosoh_selesai
from tests.pg.test_riwayat_transfer import _transfer
from tests.pg.test_riwayat_sosoh_desain_browser import browser

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_DAFTAR_RIWAYAT_PROSES')!='1',reason='Browser lokal opsional')]
OUT=Path(__file__).resolve().parents[3]/'bukti'
PATHS=['/riwayat-pengeringan','/riwayat-giling','/riwayat-sosoh','/riwayat-transfer']

@pytest_asyncio.fixture
async def contoh(pg,pabrik):
 async with pg() as db:
  u=await db.get(User,pabrik['user']);u.role=SUPERADMIN
  silo=await db.scalar(select(Silo).where(Silo.warehouse_id==pabrik['g1']).order_by(Silo.id));await db.commit()
  s1=silo.id
 dry=await _lot_selesai(pg,pabrik)
 lot=await _giling_selesai(pg,{**pabrik,'silo':s1})
 await _transfer(pg,pabrik,lot,berat=1000,lokasi='ditumpuk')
 tid=await _transfer(pg,pabrik,lot,berat=1000,lokasi='ditumpuk')
 from app.services.undo import _undo_transfer
 async with pg() as db:await _undo_transfer(db,tid);await db.commit()
 pol=await _sosoh_selesai(pg,pabrik['user'])
 return [dry,lot,pol]

async def controls(page,width):
 from playwright.async_api import expect
 await page.locator('[data-rpd-ready]').wait_for()
 assert await page.locator('.laporan-nav__jenis a').count()==5
 assert await page.locator('.laporan-nav__jenis a[aria-current=page]').count()==1
 assert await page.locator('.rpd-stats>div').count()==3
 await page.locator('[data-lk-buka=rpd-panduan]:visible').first.click();await expect(page.locator('#rpd-panduan')).to_be_visible()
 await expect(page.locator('#rpd-panduan')).to_contain_text('Ringkasan menunjukkan data di halaman')
 await page.locator('[data-rpd-guide-close]').click()
 await page.evaluate('()=>{window.__prints=0;window.print=()=>{window.__prints++}}')
 await page.locator('[data-lk-cetak]:visible').first.click();assert await page.evaluate('window.__prints')==1
 await expect(page.locator('.laporan-nav__tabs')).to_be_visible()

@pytest.mark.parametrize('width',[1440,390,320])
async def test_empat_daftar_kontrol_detail_dokumen_dan_kursor(pg,contoh,width):
 from playwright.async_api import expect
 OUT.mkdir(exist_ok=True)
 async with await _klien(pg,peran=SUPERADMIN) as c:
  async with browser(c,width) as page:
   async with pg() as db:before=await db.scalar(select(func.count()).select_from(ActivityLog))
   await page.goto(PATHS[0]);await controls(page,width)
   for i,path in enumerate(PATHS):
    if i:await page.locator('.laporan-nav__jenis a[href="'+path+'"]').click()
    await page.locator('[data-rpd-ready]').wait_for()
    assert await page.locator('.laporan-nav__jenis a[aria-current=page]').get_attribute('href')==path
    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
    assert await page.locator('.riwayat-list').count()==1 and await page.locator('.riwayat-desktop-list').count()==1
    await page.screenshot(path=str(OUT/f'{path[1:]}-{width}.png'),full_page=True)
    # Seluruh tautan rincian lama tetap membaca route dan dokumen aslinya.
    scope='.riwayat-desktop-list' if width>900 else '.riwayat-list'
    link=page.locator(scope+' a[href^="'+path+'/"]').first
    href=await link.get_attribute('href');r=await c.get(href);assert r.status_code==200
    if i<3:
     pdf=page.locator('a[href^="'+path+'/"][href$="/laporan"]').first
     response=await c.get(await pdf.get_attribute('href'));assert response.status_code==200
    if i==3:await expect(page.locator('.riwayat-desktop-list')).to_contain_text('Dibatalkan')
   await page.locator('.laporan-nav__jenis a[href="/riwayat-giling"]').click()
   await page.locator('[data-rpd-ready]').wait_for()
   href=await page.locator('.riwayat-desktop-lot a').first.get_attribute('href')
   await page.locator(('.riwayat-desktop-list' if width>900 else '.riwayat-list')+' a[href="'+href+'"]').first.click()
   await expect(page).to_have_url(re.compile('/riwayat-giling/'))
   await page.goto('/riwayat-transfer?sebelum=1');await page.locator('[data-rpd-ready]').wait_for()
   await expect(page.locator('.rpd')).to_contain_text('Tak ada lagi')
   await page.get_by_role('link',name='Kembali ke yang terbaru',exact=True).click()
   await page.locator('[data-rpd-ready]').wait_for()
   await expect(page.locator('.riwayat-desktop-list')).to_contain_text('Dibatalkan')
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==before

@pytest.mark.parametrize('gudang,lihat,boleh,terkunci',[
 ('Gudang 1','operator:g1','/riwayat-giling','/riwayat-sosoh'),
 ('Gudang 2','operator:g2','/riwayat-sosoh','/riwayat-giling')])
async def test_pilihan_terkunci_dan_scope_tetap(pg,contoh,gudang,lihat,boleh,terkunci):
 async with await _klien(pg,peran=OPERATOR,gudang=gudang,lihat=lihat) as c:
  async with browser(c,390) as page:
   await page.goto(boleh);await page.locator('[data-rpd-ready]').wait_for()
   assert await page.locator('.laporan-nav__jenis a[href="'+terkunci+'"]').count()==0
   assert await page.locator('.laporan-nav__jenis [aria-disabled=true]').count()>=1
   assert (await c.get(terkunci)).status_code==403
