"""Kontrol pendinginan aktif dengan server, formulir dan API sungguhan."""
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,DryingLot,SiloStorage
from app.penggilingan.gudang1.services import drying as dr
from tests.pg.test_detail_pendinginan_tab import pendingin,dryer_tab,pengeringan,dryer_pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser
from tests.pg.test_form_kadar_air import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_PENDINGINAN_DESAIN')!='1',reason='Browser lokal opsional')]

@pytest.fixture
async def berjalan(pg,pendingin):
 from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
 async with pg() as db:
  u=await db.get(User,pendingin['user'])
  await catat_qc_gabah(db,user=u,kode_batch=pendingin['batch'],kadar_air_1=24,kadar_air_2=25,biji_hijau='sedikit',densiti='padat',lamur=True,jumlah_sak_lamur=2)
  for n in range(21):await dr.log_cooling(db,user=u,kode_lot=pendingin['kode'],catatan=f'Catatan pendinginan uji {n}')
 return pendingin

@pytest.mark.parametrize('width',[1440,390,320])
async def test_semua_tab_paginasi_dan_selesai_asli(pg,berjalan,width):
 from playwright.async_api import expect
 d=berjalan;url='/proses-aktif/pendinginan/'+d['kode'];out=Path('../bukti-pendinginan');out.mkdir(exist_ok=True)
 async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
  before=await fakta(pg,d)
  async with browser(c,width) as page:
   await page.goto(url+'?tab_detail=bahan&kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan');await page.locator('[data-pendinginan-aktif][data-rhp-ready]').wait_for()
   assert await page.locator('.rhs-tabs [role=tab]').count()==4
   await expect(page.locator('.rhs-header h1')).to_have_text('Pendinginan aktif')
   await expect(page.locator('#panel-bahan')).to_contain_text(d['batch']);await expect(page.locator('#panel-bahan')).to_contain_text(d['tambahan']);await expect(page.locator('#panel-bahan')).to_contain_text('TK-DR-TAB');await expect(page.locator('#panel-bahan')).to_contain_text('B 4321 UJI');await expect(page.locator('#panel-bahan')).to_contain_text('24%')
   await page.locator('#panel-bahan').evaluate("e=>e.dataset.nodeUji='asli'")
   await page.screenshot(path=str(out/f'bahan-{width}.png'),full_page=True)
   await page.locator('#tab-pengukuran').click();await expect(page.locator('#panel-pengukuran')).to_contain_text('16,0%');await expect(page.locator('#panel-pengukuran')).to_contain_text('18,0%')
   await page.locator('#tab-bahan').click();assert await page.locator('#panel-bahan').get_attribute('data-node-uji')=='asli'
   await page.locator('#tab-pengukuran').click();await page.locator('#panel-pengukuran nav a').filter(has_text='Lebih lama').click();await expect(page.locator('#panel-pengukuran')).to_be_visible();assert 'tab_detail=pengukuran' in page.url and 'halaman_ukur=2' in page.url and 'kembali_kerja=' in page.url
   await page.locator('#tab-riwayat').click();await expect(page.locator('#panel-riwayat')).to_contain_text('Sedang didinginkan');await expect(page.locator('#panel-riwayat')).to_contain_text('Belum dinyatakan')
   await page.locator('#halaman_dingin nav a').filter(has_text='Lebih lama').click();await expect(page.locator('#panel-riwayat')).to_be_visible();assert 'tab_detail=riwayat' in page.url
   await page.locator('#tab-ringkasan').click();await page.locator('#tab-ringkasan').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#panel-bahan')).to_be_visible();await page.locator('#tab-ringkasan').click()
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True);assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   assert await page.locator('[data-pendinginan-aktif]').locator('[href*="/laporan"],[href$="/bobot"],progress').count()==0
   assert await fakta(pg,d)==before
   if width<=700:await page.locator('.rhs-menu>summary').click()
   await page.locator('[data-rhp-guide]:visible').click();await expect(page.locator('#rhp-panduan')).to_be_visible();await page.locator('[data-rhp-guide-close]').click()
   action=page.locator('.cold-actions a[href*="buka=selesai_pendinginan"]');assert await action.count()==1
   await action.click();await page.locator('#lembar[open]').wait_for();await expect(page.locator('#lembar')).to_contain_text(d['kode'])
   assert await fakta(pg,d)==before
   await page.keyboard.press('Escape');await page.locator('#lembar').wait_for(state='hidden');await expect(page.locator('#panel-ringkasan')).to_be_visible()
   await action.click();await page.locator('#lembar[open]').wait_for();await page.screenshot(path=str(out/f'konfirmasi-{width}.png'),full_page=True)
   await page.locator('#simpan').click();await page.locator('#lembar').wait_for(state='hidden')
   await expect(page.locator('.rhs-header h1')).to_have_text('Riwayat pengeringan')
   assert await page.locator('[data-pendinginan-aktif]').count()==0
   await expect(page.locator('[data-riwayat-pengeringan]')).to_contain_text('Sudah dingin')
   assert await page.locator('#tindakan-proses a[href*="buka=pindah_silo"]').count()==1
   assert await page.locator('#tindakan-proses a[href*="buka=mulai_pendinginan_ulang"]').count()==1
   async with pg() as db:
    lot=await db.get(DryingLot,d['id']);assert lot.waktu_selesai_pendinginan is not None
    assert await db.scalar(select(func.count()).select_from(SiloStorage))==0
   assert (await c.get('/riwayat-pengeringan/'+str(d['id'])+'/laporan.pdf')).content.startswith(b'%PDF')
   await page.screenshot(path=str(out/f'selesai-{width}.png'),full_page=True)

async def test_operator_hash_fallback_print_dan_gudang_lain(pg,berjalan):
 from playwright.async_api import expect
 from bs4 import BeautifulSoup
 url='/proses-aktif/pendinginan/'+berjalan['kode']
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  async with browser(c,320) as page:
   await page.goto(url+'#putaran-pendinginan');await expect(page.locator('#panel-riwayat')).to_be_visible()
   await page.emulate_media(media='print')
   for id in ['bahan','pengukuran','riwayat']:await expect(page.locator('#panel-'+id)).to_be_visible()
   await page.emulate_media(media='screen');assert await page.locator('.cold-actions a').count()==1
  for id in ['ringkasan','bahan','pengukuran','riwayat']:
   r=await c.get(url+'?tab_detail='+id);html=BeautifulSoup(r.text,'html.parser');assert r.status_code==200 and 'hidden' not in html.select_one('#panel-'+id).attrs
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:assert (await c.get(url)).status_code==403
