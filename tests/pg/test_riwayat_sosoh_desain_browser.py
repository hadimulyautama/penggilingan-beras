"""Tab riwayat memakai node formulir dan API asli pada PostgreSQL lokal."""
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,PolishingProcess,PolishingOutputLog,SampelQcSosoh,ActivityLog
from app.services import qc_sosoh as qc
from app.penggilingan.gudang2 import polishing as p
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from contextlib import asynccontextmanager
@asynccontextmanager
async def browser(c,width):
 import asyncio,socket,uvicorn
 from app.main import app
 from playwright.async_api import async_playwright
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 base=f'http://127.0.0.1:{port}'
 server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,lifespan='off',access_log=False,log_level='error'))
 task=asyncio.create_task(server.serve())
 while not server.started:
  if task.done():await task
  await asyncio.sleep(.01)
 try:
  async with async_playwright() as pw:
   b=await pw.chromium.launch();page=await b.new_page(base_url=base,viewport=dict(width=width,height=1000),service_workers='block');errors=[]
   page.on('pageerror',lambda e:errors.append(e.stack))
   await page.context.add_cookies([dict(name=k.name,value=k.value,url=base) for k in c.cookies.jar])
   await page.route('https://**/*',lambda r:r.abort())
   try:yield page
   finally:
    await b.close()
    assert not errors,errors
 finally:
  server.should_exit=True
  await task

from tests.pg.test_riwayat_sosoh import _klien
from tests.pg.formulir import cap_formulir
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_RIWAYAT_SOSOH')!='1',reason='Browser lokal opsional')]

@pytest.fixture
async def riwayat(pg,running):
 uid,kode,_,_=running
 async with pg() as db:
  u=await db.get(User,uid);pr=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode));pid=pr.id;at=pr.waktu_mulai
  a=await qc.ambil_sampel(db,user=u,kode_proses=kode,jenis='medium',waktu_sampel=at)
  b=await qc.ambil_sampel(db,user=u,kode_proses=kode,jenis='premium',waktu_sampel=at)
  await qc.isi_hasil(db,user=u,sampel_id=a.id,kadar_air='13.5',broken_persen='8',md='90',transparant='2.1',whiteness='42',catatan_lab='Sampel awal')
  await p.akhiri_penyosohan(db,user=u,kode=kode)
 return dict(id=pid,kode=kode,q=b.id,uid=uid)

@pytest.mark.parametrize('width',[1440,390,320])
async def test_tab_draf_koreksi_qc_pdf_dan_asal_asli(pg,riwayat,width):
 from playwright.async_api import expect
 out=Path(os.getenv('BUKTI_RIWAYAT_SOSOH','../bukti'));out.mkdir(parents=True,exist_ok=True)
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with browser(c,width) as page:
   await page.goto('/riwayat-sosoh/'+str(riwayat['id']))
   await page.locator('[data-rhs-ready]').wait_for();assert await page.locator('[data-rhs-tab]').count()==5
   await expect(page.locator('#rhs-panel-ringkasan')).to_contain_text('2.500 kg')
   assert await page.locator('#rhs-tab-ringkasan').evaluate("e=>getComputedStyle(e).backgroundColor")=='rgba(0, 0, 0, 0)'
   async with pg() as db:before=await db.scalar(select(func.count()).select_from(ActivityLog))
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   await page.locator('#rhs-tab-ringkasan').focus();await page.keyboard.press('ArrowRight')
   await expect(page.locator('#rhs-tab-bahan')).to_have_attribute('aria-selected','true')
   await expect(page.locator('#rhs-panel-bahan')).to_contain_text('Silo A')
   await page.screenshot(path=str(out/f'bahan-{width}.png'),full_page=True)
   await page.locator('[data-rhs-edit]:visible').first.click()
   field=page.locator('[name=hasil_medium]');await field.fill('2100')
   assert await page.locator('[name^=hasil_]').count()==9
   await page.locator('[name=alasan]').fill('Pemeriksaan hasil fisik')
   await field.evaluate("e=>e.dataset.nodeUji='asli'")
   await page.locator('[data-rhs-tab=qc]').click()
   await page.locator('[data-qc-lengkapi]').click()
   editor=page.locator('[data-qc-editor]');await editor.wait_for(state='visible')
   assert await editor.locator('input[inputmode=decimal]').count()==5
   await editor.locator('[name=kadar_air]').fill('13,455')
   await page.locator('[data-rhs-tab=hasil]').click();assert await field.input_value()=='2100'
   assert await field.get_attribute('data-node-uji')=='asli'
   await page.locator('[data-rhs-tab=qc]').click();assert await editor.locator('[name=kadar_air]').input_value()=='13,455'
   for name,v in [('broken_persen','9,995'),('md','123,456'),('transparant','1,005'),('whiteness','45,678')]:await editor.locator('[name='+name+']').fill(v)
   await page.screenshot(path=str(out/f'qc-{width}.png'),full_page=True)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==before
   await editor.locator('[data-qc-simpan]').click()
   await expect(page.locator('[data-qc-sosoh]')).to_contain_text('Kadar air 13,46%')
   await page.locator('[data-rhs-tab=hasil]').click();assert await field.input_value()=='2100'
   form=page.locator('.riwayat-koreksi__form');await form.get_by_role('button',name='Periksa koreksi',exact=True).click()
   await expect(page.locator('[data-rhs-review]')).to_contain_text('2000.00 → 2100 kg')
   async with pg() as db:assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2200
   await form.get_by_role('button',name='Konfirmasi & simpan koreksi',exact=True).click()
   await expect(page.locator('#rhs-panel-hasil')).to_contain_text('Koreksi hasil tersimpan')
   assert await page.locator('#rhs-tab-hasil').get_attribute('aria-selected')=='true'
   async with pg() as db:
    assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2300
    q=await db.get(SampelQcSosoh,riwayat['q']);assert float(q.kadar_air)==13.46 and float(q.md)==123.46
   await page.locator('.rhs-pack>summary').click()
   assert await page.locator('.rhs-pack a').count()==4
   for a in await page.locator('.rhs-pack a').all():
    r=await c.get(await a.get_attribute('href'));assert r.status_code==200
   r=await c.get('/riwayat-sosoh/'+str(riwayat['id'])+'/laporan');assert r.status_code==200
   r=await c.get('/riwayat-sosoh/'+str(riwayat['id'])+'/laporan.pdf');assert r.status_code==200 and 'application/pdf' in r.headers['content-type']
   await page.locator('[data-rhs-tab=riwayat]').click();await expect(page.locator('#rhs-panel-riwayat')).to_contain_text('Informasi proses')
   if width<=700:await page.locator('.rhs-menu>summary').click()
   await page.locator('[data-rhs-guide]:visible').click();await expect(page.locator('#rhs-panduan')).to_be_visible();await page.locator('[data-rhs-guide-close]').click()
   await page.locator('.rhs-menu>summary').click();await page.locator('[data-rhs-nav-open]').click()
   await expect(page.locator('#rhs-navigation')).to_be_visible()
   assert await page.locator('#rhs-navigation .laporan-nav__tabs a').count()>=3
   await page.locator('[data-rhs-nav-close]').click()

async def test_operator_tanpa_koreksi_dan_hash_qc(pg,riwayat):
 from playwright.async_api import expect
 async with await _klien(pg,peran='operator',gudang='Gudang 2',lihat='operator:g2') as c:
  async with browser(c,390) as page:
   await page.goto('/riwayat-sosoh/'+str(riwayat['id'])+'#qc-sosoh')
   await expect(page.locator('#rhs-panel-qc')).to_be_visible()
   assert await page.locator('[data-rhs-edit],.riwayat-koreksi__form,[data-qc-lengkapi],.rhs-pack').count()==0
   await page.locator('[data-rhs-tab=hasil]').click()
   await expect(page.locator('.rhs-all-results')).to_contain_text('2.000 kg')
   assert await page.locator('.rhs-all-results>div').count()==9

async def test_data_berubah_isian_dan_pemeriksaan_ulang_tetap(pg,riwayat):
 from playwright.async_api import expect
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with browser(c,390) as page:
   await page.goto('/riwayat-sosoh/'+str(riwayat['id']))
   await page.locator('[data-rhs-edit]:visible').first.click()
   await page.locator('[name=hasil_medium]').fill('2100');await page.locator('[name=alasan]').fill('Uji perubahan bersamaan')
   async with pg() as db:
    dasar={j:0 for j in p._ALL_JENIS};dasar.update(medium=2000,broken=200)
    await p.koreksi_hasil_sosoh(db,user=await db.get(User,riwayat['uid']),process_id=riwayat['id'],perubahan={**dasar,'medium':2050},dasar=dasar,alasan='Catatan lain diperbarui')
   await page.get_by_role('button',name='Periksa koreksi',exact=True).click()
   await page.locator('[data-rhs-confirm]').click()
   await expect(page.locator('[name=periksa_ulang]')).to_be_visible()
   await expect(page.locator('[data-rhs-ready]')).to_be_visible()
   assert await page.locator('[name=hasil_medium]').input_value()=='2100'
   assert await page.locator('[name=alasan]').input_value()=='Uji perubahan bersamaan'
   await expect(page.locator('#rhs-panel-hasil')).to_contain_text('Catatan berubah')
   await page.locator('[name=periksa_ulang]').check()
   await page.get_by_role('button',name='Periksa koreksi',exact=True).click();await page.locator('[data-rhs-confirm]').click()
   await expect(page.locator('#rhs-panel-hasil')).to_contain_text('Koreksi hasil tersimpan')
   await page.locator('[data-rhs-tab=qc]').click()
   link=page.locator('a[href*="buka=batalkan_sampel_qc_sosoh"][href*="nilai='+str(riwayat['q'])+'"]')
   await link.click();await page.locator('#lembar[open]').wait_for()
