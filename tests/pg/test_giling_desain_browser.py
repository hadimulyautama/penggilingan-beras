"""Penyajian aktif di browser dengan API asli dan PostgreSQL lokal."""
from tests.pg.test_pengeringan_desain_browser import browser
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import ActivityLog,MillingQcLog
from app.penggilingan.gudang1.services import milling as m
from tests.pg.test_form_hasil_penggilingan import hasil,g1,fakta
from tests.pg.test_form_selesai_penggilingan import lepas
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_GILING_DESAIN')!='1',reason='Browser lokal opsional')]

@pytest.mark.parametrize('width',[1440,390,320])
async def test_editor_tunggal_tab_draf_qc_sumber_stok_dan_simpan(pg,hasil,width):
 from playwright.async_api import expect
 u,pr,_=hasil
 async with pg() as db:await m.verify_milling_output(db,user=u,kode_proses=pr.kode_proses,berat_output=5900)
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  before=await fakta(pg,pr)
  async with browser(c,width) as page:
   await page.goto('https://uji/proses-aktif/giling/'+pr.kode_proses)
   await page.locator('.sr-design-tabs').wait_for();assert await page.locator('[data-sr-tab]').count()==5
   await expect(page.locator('[data-sr-panel=ringkasan]')).to_contain_text('5.900 kg')
   assert await page.locator('[data-sr-tab=ringkasan]').evaluate("e=>getComputedStyle(e).backgroundColor")=='rgba(0, 0, 0, 0)'
   out=Path(os.getenv('BUKTI_GILING_DESAIN','../bukti'));out.mkdir(parents=True,exist_ok=True)
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   await page.locator('[data-sr-tab=ringkasan]').focus();await page.keyboard.press('ArrowRight')
   assert await page.locator('[data-sr-tab=bahan]').get_attribute('aria-selected')=='true'
   await expect(page.locator('#sumber')).to_contain_text('Silo A')
   await expect(page.locator('#sumber')).to_contain_text('Silo B')
   source=page.locator('[data-kb-entry]').first;await source.wait_for()
   await source.get_by_role('button',name='Ubah',exact=True).click()
   await page.locator('[data-koreksi-bahan]').wait_for(state='visible')
   assert await page.locator('[data-sr-tab=hasil]').is_disabled()
   await page.get_by_role('button',name='Tutup koreksi',exact=True).click()
   assert await page.locator('[data-sr-tab=hasil]').is_enabled()
   await page.screenshot(path=str(out/f'bahan-{width}.png'),full_page=True)
   await page.locator('[data-sr-tab=ringkasan]').click()
   field=page.get_by_role('spinbutton',name='Total PK kumulatif',exact=True)
   await field.evaluate("e=>e.dataset.nodeUji='sama'");await field.fill('6400')
   await page.locator('[data-sr-tab=hasil]').click()
   assert await field.get_attribute('data-node-uji')=='sama';assert await field.input_value()=='6400'
   await page.locator('[data-sr-tab=qc]').click()
   await expect(page.locator('#qc')).to_contain_text('QC hasil PK')
   await page.get_by_role('button',name='Catat putaran QC',exact=True).click()
   assert await page.locator('[data-sr-tab=hasil]').is_disabled()
   for name,value in [('Kadar air (%)','13.5'),('Butir patah (%)','22'),('Susut uji (%)','12')]:await page.get_by_role('spinbutton',name=name,exact=True).fill(value)
   for name,value in [('Butir kuning','sedikit'),('Kandungan gabah','bersih'),('Merang','sedikit')]:await page.get_by_role('combobox',name=name,exact=True).select_option(value)
   await page.get_by_role('textbox',name='Catatan lab (opsional)',exact=True).fill('Sampel giling asli')
   await page.screenshot(path=str(out/f'qc-{width}.png'),full_page=True)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   assert await fakta(pg,pr)==before
   await page.get_by_role('button',name='Periksa sebelum simpan',exact=True).click()
   await page.locator('[data-review]').wait_for();await expect(page.locator('[data-review]')).to_contain_text('Sampel giling asli')
   await page.get_by_role('button',name='Konfirmasi pencatatan',exact=True).click()
   await page.locator('[data-pesan]').filter(has_text='tercatat').wait_for()
   await page.locator('[data-sr-tab=hasil]').click();assert await field.input_value()=='6400'
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(MillingQcLog))==1
   await page.get_by_role('button',name='Periksa & catat PK',exact=True).click()
   await page.locator('[data-review]').wait_for()
   await expect(page.locator('[data-review]')).to_contain_text('5.900 kg')
   await expect(page.locator('[data-review]')).to_contain_text('400 kg')
   await page.get_by_role('button',name='Konfirmasi pencatatan',exact=True).click()
   await page.locator('[data-pesan]').filter(has_text='tercatat').wait_for()
   f=await fakta(pg,pr);assert f['logs'][-1][0]==6400;assert f['stok'].produced==5900 and f['stok'].tersedia==5900
   await page.locator('[data-sr-tab=ringkasan]').click();assert await field.input_value()=='6400'
   await page.locator('[data-sr-tab=riwayat]').click()
   await expect(page.locator('[data-sr-panel=riwayat]')).to_contain_text('PK kumulatif 6.400 kg')
   if width<=650:await page.locator('summary[aria-label="Tindakan proses"]').click()
   help_button=page.get_by_role('button',name='ⓘ Panduan',exact=True).filter(visible=True)
   await help_button.click();await expect(page.locator('#gr-panduan')).to_be_visible()
   await page.locator('[data-gr-guide-close]').click()

async def test_penyelesaian_asli_draf_dan_riwayat_tetap(pg,hasil):
 from playwright.async_api import expect
 u,pr,_=hasil;await lepas(pg,u,pr)
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with browser(c,390) as page:
   await page.goto('https://uji/proses-aktif/giling/'+pr.kode_proses)
   field=page.get_by_role('spinbutton',name='Total PK kumulatif',exact=True);await field.fill('6200')
   await page.get_by_role('button',name='Periksa selesai',exact=True).click()
   await expect(page.locator('[data-action-panel]')).to_contain_text('Selesaikan tidak mengirim isian tersebut diam-diam')
   await page.get_by_role('button',name='Periksa isian PK',exact=True).click()
   assert await field.input_value()=='6200';assert await field.is_visible()
   await page.get_by_role('button',name='Periksa & catat PK',exact=True).click()
   await page.get_by_role('button',name='Konfirmasi pencatatan',exact=True).click()
   await page.locator('[data-pesan]').filter(has_text='tercatat').wait_for()
   await page.get_by_role('button',name='Periksa selesai',exact=True).click()
   await page.get_by_role('button',name='Periksa hasil & selesai',exact=True).click()
   await page.locator('[data-confirm-finish]').wait_for()
   b=page.get_by_role('button',name='Konfirmasi selesai penggilingan',exact=True);assert await b.is_disabled()
   await page.locator('[data-confirm-finish]').check();assert await b.is_enabled();await b.click()
   await expect(page.locator('[data-proses-isi]>header')).to_contain_text('Selesai')
   assert await page.locator('.gr-redesign').count()==0;assert await page.locator('.sr-design-tabs').count()==0
   f=await fakta(pg,pr);assert f['status']=='selesai' and f['logs'][-1][0]==6200

async def test_legacy_bahan_dan_jeda_tetap_terlihat(pg,hasil):
 from playwright.async_api import expect
 _,pr,_=hasil
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with browser(c,390) as page:
   await page.goto('https://uji/proses-aktif/giling/'+pr.kode_proses+'?buka=tutup_silo_giling')
   assert await page.locator('[data-sr-tab=bahan]').get_attribute('aria-selected')=='true'
   await page.get_by_role('button',name='Periksa sisa & bebaskan',exact=True).first.click()
   await expect(page.locator('[data-action-panel]')).to_contain_text('Kosong bukan nol')
   await page.get_by_role('button',name='Tutup formulir',exact=True).click()
   await page.get_by_role('button',name='Jeda mesin',exact=True).click()
   await page.get_by_role('combobox',name='Sebab berhenti',exact=True).wait_for()
   await expect(page.locator('[data-action-panel]')).to_be_visible()
   assert await page.locator('[data-sr-tab=qc]').is_disabled()
   await page.get_by_role('combobox',name='Sebab berhenti',exact=True).select_option(label='Listrik padam')
   await page.get_by_role('button',name='Periksa sebelum simpan',exact=True).click()
   await page.get_by_role('button',name='Konfirmasi pencatatan',exact=True).click()
   await expect(page.locator('[data-proses-isi]>header')).to_contain_text('Dijeda')
   assert await page.get_by_role('button',name='Perbarui kondisi jeda',exact=True).is_visible()
