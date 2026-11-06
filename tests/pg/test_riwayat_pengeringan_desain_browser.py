"""Riwayat selesai dengan empat tab, API dan formulir bobot asli."""
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,DryingLot,ActivityLog,SiloStorage,PurchaseBatch
from app.penggilingan.gudang1.services import drying as dr
from tests.pg.test_detail_pendinginan_tab import pendingin,dryer_tab,pengeringan,dryer_pabrik
from tests.pg.test_riwayat_sosoh_desain_browser import browser
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from tests.pg.test_form_kadar_air import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_RIWAYAT_PENGERINGAN')!='1',reason='Browser lokal opsional')]

@pytest.fixture
async def riwayat(pg,pendingin):
 from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
 async with pg() as db:
  u=await db.get(User,pendingin['user'])
  await catat_qc_gabah(db,user=u,kode_batch=pendingin['batch'],kadar_air_1=24,kadar_air_2=25,biji_hijau='sedikit',densiti='padat',lamur=True,jumlah_sak_lamur=2)
  for n in range(21):await dr.log_cooling(db,user=u,kode_lot=pendingin['kode'],catatan=f'Pemeriksaan dingin {n}')
  await dr.finish_cooling(db,user=u,kode_lot=pendingin['kode'])
 return pendingin

@pytest.mark.parametrize('width',[1440,390,320])
async def test_tab_data_paginasi_tindakan_bobot_pdf_dan_panduan(pg,riwayat,width):
 from playwright.async_api import expect
 kode=riwayat['kode'];lid=riwayat['id'];url='/riwayat-pengeringan/'+str(lid);out=Path('../bukti');out.mkdir(exist_ok=True)
 async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);before=await fakta(pg,riwayat)
  async with browser(c,width) as page:
   await page.goto(url+'?tab_detail=bahan&kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan')
   await page.locator('[data-rhp-ready]').wait_for();assert await page.locator('.rhs-tabs [role=tab]').count()==4
   batch=page.locator('#panel-bahan');await expect(batch).to_contain_text(riwayat['batch']);await expect(batch).to_contain_text(riwayat['tambahan']);await expect(batch).to_contain_text('TK-DR-TAB');await expect(batch).to_contain_text('B 4321 UJI');await expect(batch).to_contain_text('24%');await expect(batch).to_contain_text('Ya · 2 sak')
   await batch.evaluate("e=>e.dataset.uji='asli'");await page.screenshot(path=str(out/f'bahan-{width}.png'),full_page=True)
   await page.locator('#tab-pengukuran').click();await expect(page.locator('#panel-pengukuran')).to_contain_text('16,0%');await expect(page.locator('#panel-pengukuran')).to_contain_text('18,0%')
   await page.screenshot(path=str(out/f'pengukuran-{width}.png'),full_page=True)
   await page.locator('#panel-pengukuran nav a').filter(has_text='Lebih lama').click()
   await expect(page.locator('#panel-pengukuran')).to_be_visible();assert 'tab_detail=pengukuran' in page.url and 'halaman_ukur=2' in page.url and 'kembali_kerja=' in page.url
   await page.locator('#tab-riwayat').click();await expect(page.locator('#panel-riwayat')).to_contain_text('Waktu pendinginan');await expect(page.locator('#panel-riwayat')).to_contain_text('Total jeda pengeringan')
   await page.locator('#halaman_dingin nav a').filter(has_text='Lebih lama').click();await expect(page.locator('#panel-riwayat')).to_be_visible();assert 'tab_detail=riwayat' in page.url and 'halaman_dingin=2' in page.url
   await page.locator('#tab-ringkasan').click();await page.locator('#tab-ringkasan').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#panel-bahan')).to_be_visible()
   await page.locator('#tab-ringkasan').click();await expect(page.locator('#panel-ringkasan')).to_contain_text('10.000 kg');await expect(page.locator('#panel-ringkasan')).to_contain_text('Sudah dingin, menunggu dipindah ke silo')
   assert await page.locator('a[href$="/bobot"]').count()==0
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True);assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   assert await fakta(pg,riwayat)==before
   # Dua pintu tindakan tetap memakai formulir katalog asli.
   await page.locator('#tindakan-proses a[href*="buka=pindah_silo"]').click();await page.locator('#lembar[open]').wait_for();await expect(page.locator('#lembar')).to_contain_text('silo')
   await page.keyboard.press('Escape');await page.locator('#lembar').wait_for(state='hidden')
   await page.locator('#tindakan-proses a[href*="buka=mulai_pendinginan_ulang"]').click();await page.locator('#lembar[open]').wait_for();await page.keyboard.press('Escape');await page.locator('#lembar').wait_for(state='hidden')
   if width<=700:await page.locator('.rhs-menu>summary').click()
   await page.locator('[data-rhp-guide]:visible').click();await expect(page.locator('#rhp-panduan')).to_be_visible();await page.locator('[data-rhp-guide-close]').click()
   await page.locator('.rhs-menu>summary').click();await page.locator('[data-rhp-nav-open]').click();await expect(page.locator('#rhp-navigation')).to_be_visible();assert await page.locator('#rhp-navigation .laporan-nav__tabs a').count()>=3;await page.locator('[data-rhp-nav-close]').click()
   # Pindah ke silo lewat API yang sama, kemudian catat flowing scale lewat UI asli.
   r=await c.post('/api/actions/pindah-silo',json={'kode_lot':kode,'silo':'A'});assert r.status_code==200,r.text
   await page.goto(url);await expect(page.locator('#panel-ringkasan')).to_contain_text('Sudah dipindah ke Silo A')
   assert await page.locator('#tindakan-proses a').count()==0
   await page.get_by_role('link',name='Catat hasil timbang flowing scale',exact=True).click();await page.locator('[data-form-bobot]').wait_for()
   await page.locator('[name=kg]').fill('8500.25');await page.locator('[name=referensi]').fill('FS-UJI-'+str(width));await page.locator('[name=konfirmasi]').check()
   await page.get_by_role('button',name='Periksa catatan timbang',exact=True).click();await expect(page.locator('[data-preview]')).to_be_visible()
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='catat_bobot_kering_terukur'))==0
   await page.locator('[data-simpan]').click();await expect(page.locator('[data-pesan]')).to_contain_text('flowing scale tercatat')
   await page.get_by_role('link',name='Kembali ke proses',exact=True).click();await expect(page.locator('.bobot-pengeringan')).to_contain_text('8.500,25 kg')
   await page.screenshot(path=str(out/f'terukur-{width}.png'),full_page=True)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   for suffix in ['/laporan','/laporan.pdf','/laporan.pdf?unduh=1']:
    r=await c.get(url+suffix);assert r.status_code==200
    if '.pdf' in suffix:assert r.content.startswith(b'%PDF')
   async with pg() as db:
    assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='catat_bobot_kering_terukur'))==1
    assert await db.scalar(select(func.count()).select_from(SiloStorage))==1

async def test_hash_print_fallback_dan_pendinginan_aktif_tetap(pg,riwayat):
 from playwright.async_api import expect
 from bs4 import BeautifulSoup
 url='/riwayat-pengeringan/'+str(riwayat['id'])
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  async with browser(c,320) as page:
   await page.goto(url+'#putaran-pendinginan');await expect(page.locator('#panel-riwayat')).to_be_visible()
   await page.emulate_media(media='print')
   for id in ['bahan','pengukuran','riwayat']:await expect(page.locator('#panel-'+id)).to_be_visible()
   await page.emulate_media(media='screen')
   assert await page.locator('.rhs-tabs').is_visible()
  for id in ['ringkasan','bahan','pengukuran','riwayat']:
   r=await c.get(url+'?tab_detail='+id);html=BeautifulSoup(r.text,'html.parser');assert r.status_code==200 and 'hidden' not in html.select_one('#panel-'+id).attrs
  async with pg() as db:await dr.mulai_pendinginan_ulang(db,user=await db.get(User,riwayat['user']),kode_lot=riwayat['kode'])
  r=await c.get(url);assert r.status_code==200 and r.url.path.startswith('/proses-aktif/pendinginan/')
  assert 'data-riwayat-pengeringan' not in r.text and 'data-pendinginan-aktif' in r.text and '/static/riwayat-pengeringan-desain.js?' in r.text
