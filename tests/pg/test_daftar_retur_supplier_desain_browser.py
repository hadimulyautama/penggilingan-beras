"""Pencarian/filter asli tetap satu GET form pada desktop dan ponsel."""
import os
from pathlib import Path
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.models.retur_supplier import ReturSupplier
from tests.pg.test_retur_supplier import asal,skema_retur_timbang,buat
from tests.pg.test_riwayat_retur_supplier import selesai,sidik_semua
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_DAFTAR_RETUR_SUPPLIER')!='1',reason='Browser lokal opsional')]
OUT=Path(__file__).resolve().parents[3]/'bukti'

@pytest_asyncio.fixture
async def daftar(pg,asal,monkeypatch):
 from app.services import riwayat_retur_supplier as svc
 async with pg() as db:
  a,_,_=await selesai(db,asal);b,_,_=await selesai(db,asal)
  pending=await buat(db,asal,n='1')
  for r in [a,b,pending]:r.sumber=dict(r.sumber,nota='NOTA-DAFTAR-ASLI')
  await db.commit()
 monkeypatch.setattr(svc,'UKURAN_HALAMAN',1)
 return {**asal,'ids':[a.id,b.id,pending.id]}

async def open_filter(page,width):
 from playwright.async_api import expect
 scope=page.locator('.rhs-tools') if width<=700 else page.locator('#rrs-form')
 await scope.locator('[data-rrs-filter-open]').click()
 await expect(page.locator('#rrs-filter')).to_be_visible()

@pytest.mark.parametrize('width',[1440,390,320])
async def test_cari_filter_konteks_rekap_paging_dan_reset_asli(pg,daftar,width):
 from playwright.async_api import expect
 OUT.mkdir(exist_ok=True)
 async with pg() as db:before=await sidik_semua(db)
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  async with browser(c,width) as page:
   await page.goto('/riwayat-retur-supplier');await page.locator('[data-rrs-ready]').wait_for()
   assert await page.locator('.laporan-nav__jenis a').count()==5
   assert await page.locator('.rrs-metrik>div').count()==3
   await expect(page.locator('.rrs-rekap')).to_contain_text('499 kg')
   if width>700:
    button=await page.locator('#rrs-form [data-rrs-filter-open]').bounding_box();field=await page.locator('[name=q]').bounding_box()
    assert abs(button['y']-field['y'])<=4
    assert button['width']<200 and field['width']>300
    assert field['x']+field['width']<1440
   else:
    button=await page.locator('.rhs-tools [data-rrs-filter-open]').bounding_box();field=await page.locator('[name=q]').bounding_box()
    assert button['y']<field['y']
   assert not await page.locator('.rrs').evaluate('e=>e.scrollWidth>e.clientWidth')
   await page.screenshot(path=str(OUT/f'daftar-{width}.png'),full_page=True)
   await page.locator('[name=q]').fill('NOTA-DAFTAR-ASLI')
   await open_filter(page,width)
   assert await page.locator('#rrs-filter select[name=status] option').count()==13
   assert await page.locator('#rrs-filter [form=rrs-form]').count()==6
   await page.locator('#rrs-filter [name=status]').select_option('ready');await page.keyboard.press('Escape')
   await open_filter(page,width)
   assert await page.locator('#rrs-filter [name=status]').input_value()=='ready'
   assert await page.locator('[name=q]').input_value()=='NOTA-DAFTAR-ASLI'
   await page.locator('#rrs-filter [name=status]').select_option('done')
   await page.locator('#rrs-filter [name=supplier]').select_option(str(daftar['sid']))
   await page.locator('#rrs-filter [name=gudang]').select_option(str(daftar['wh']))
   await page.locator('#rrs-filter [name=awal]').fill('2000-01-01');await page.locator('#rrs-filter [name=akhir]').fill('2099-12-31')
   await page.screenshot(path=str(OUT/f'filter-{width}.png'),full_page=True)
   await page.locator('#rrs-filter button[type=submit]').click();await page.locator('[data-rrs-ready]').wait_for()
   assert 'status=done' in page.url and 'q=NOTA-DAFTAR-ASLI' in page.url and 'awal=2000-01-01' in page.url
   await expect(page.locator('.rrs-rekap')).to_contain_text('499 kg')
   await page.get_by_role('link',name='Berikutnya',exact=True).click();await page.locator('[data-rrs-ready]').wait_for()
   assert 'halaman=2' in page.url;await expect(page.locator('.rrs-rekap')).to_contain_text('499 kg')
   scope='.rsh-tabel' if width>900 else '.rsh-kartu-daftar'
   detail=page.locator(scope+' a[href^="/riwayat-retur-supplier/"]').first
   href=await detail.get_attribute('href');assert 'halaman=2' in href and 'q=NOTA-DAFTAR-ASLI' in href
   await detail.click();await page.locator('[data-rsd-ready]').wait_for()
   await page.locator('.rsp-kembali').click();await page.locator('[data-rrs-ready]').wait_for()
   assert 'halaman=2' in page.url
   # Enter mengirim seluruh field yang dimiliki form, termasuk yang berada
   # di dialog. Jangan mengirim hanya q atau mengosongkan gudang/penerimaan.
   await page.locator('[name=q]').press('Enter');await page.locator('[data-rrs-ready]').wait_for()
   assert 'status=done' in page.url and 'gudang='+str(daftar['wh']) in page.url
   await page.evaluate('()=>{window.__prints=0;window.print=()=>window.__prints++}')
   await page.locator('[data-lk-cetak]:visible').first.click();assert await page.evaluate('window.__prints')==1
   await page.goto('/riwayat-retur-supplier?penerimaan='+str(daftar['tid'])+'&q=NOTA-DAFTAR-ASLI&status=done')
   await page.locator('[data-rrs-ready]').wait_for();await open_filter(page,width)
   data=await page.evaluate('()=>Object.fromEntries(new FormData(document.getElementById("rrs-form")))')
   assert data['penerimaan']==str(daftar['tid']) and data['q']=='NOTA-DAFTAR-ASLI' and data['status']=='done'
   await page.locator('#rrs-filter .rsh-filter>a').click();await page.locator('[data-rrs-ready]').wait_for()
   assert 'penerimaan='+str(daftar['tid']) in page.url and 'status=' not in page.url
   await expect(page.locator('[aria-label="Cakupan penerimaan"]')).to_contain_text('Riwayat dibatasi')
   await page.get_by_role('link',name='Lihat semua penerimaan yang diizinkan').click();await page.locator('[data-rrs-ready]').wait_for()
   assert 'penerimaan=' not in page.url
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await page.locator('[data-lk-buka=rpd-panduan]:visible').first.click();await expect(page.locator('#rpd-panduan')).to_contain_text('tidak menambah stok');await page.locator('[data-rpd-guide-close]').click()
 async with pg() as db:assert await sidik_semua(db)==before

async def test_error_dan_fallback_tanpa_skrip_penataan(pg,daftar):
 from playwright.async_api import expect
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  async with browser(c,390) as page:
   await page.goto('/riwayat-retur-supplier?awal=2026-11-06&akhir=2026-11-01&q=isian+tetap')
   await page.locator('[data-rrs-ready]').wait_for();await expect(page.locator('.rrs')).to_contain_text('Rentang tanggal tidak sah')
   await open_filter(page,390)
   assert await page.locator('#rrs-filter [name=awal]').input_value()=='2026-11-06'
   assert await page.locator('[name=q]').input_value()=='isian tetap'
   await page.keyboard.press('Escape')
   await page.route('**/static/daftar-retur-supplier-desain.js*',lambda r:r.abort())
   await page.goto('/riwayat-retur-supplier?status=done')
   await expect(page.locator('#rrs-form .rsh-filter')).to_be_visible()
   assert await page.locator('#rrs-form [name=status]').input_value()=='done'
   assert await page.locator('#rrs-form [data-rrs-filter-open]:visible').count()==0
