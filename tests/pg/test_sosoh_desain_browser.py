"""Semua aksi browser memakai API asli dan PostgreSQL uji; tak ada handler tiruan."""
from tests.profil_browser import mesin, konteks
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from sqlalchemy import select,func
from app.models import PolishingOutputLog,ActivityLog
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_SOSOH_DESAIN')!='1',reason='Browser lokal opsional')]

@pytest.mark.parametrize('width',[1440,390,320])
async def test_tab_draf_qc_sumber_dan_editor_asli(pg,running,width):
 from playwright.async_api import async_playwright,expect
 out=Path(os.environ.get('BUKTI_SOSOH_DESAIN','../bukti'));out.mkdir(parents=True,exist_ok=True)
 uid,kode,mid,intake=running
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with pg() as db:
   before=await db.scalar(select(func.count()).select_from(ActivityLog))
  async with async_playwright() as pw:
   browser=await mesin(pw).launch();page=await browser.new_page(**konteks(pw,width,1000));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   await page.context.add_cookies([dict(name=k.name,value=k.value,url='https://uji') for k in c.cookies.jar])
   async def route(r):
    req=r.request;u=urlsplit(req.url)
    if u.netloc!='uji':await r.abort();return
    headers={k:v for k,v in req.headers.items() if k.lower() not in ('host','cookie','content-length')}
    response=await c.request(req.method,req.url,headers=headers,content=req.post_data_buffer)
    await r.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','set-cookie')})
   await page.route('**/*',route)
   await page.goto('https://uji/proses-aktif/sosoh/'+kode)
   await page.locator('.sr-design-tabs').wait_for();assert await page.locator('[data-sr-tab]').count()==5
   assert await page.locator('[data-proses-isi]>header').get_by_text('Mulai',exact=False).is_visible()
   assert await page.locator('[data-sr-tab="ringkasan"]').evaluate("e=>getComputedStyle(e).backgroundColor")=='rgba(0, 0, 0, 0)'
   await page.locator('[data-sr-tab="ringkasan"]').focus();await page.keyboard.press('ArrowRight')
   assert await page.locator('[data-sr-tab="bahan"]').get_attribute('aria-selected')=='true'
   await page.keyboard.press('ArrowLeft')
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   await page.get_by_role('button',name='Catat hasil',exact=True).click()
   result=page.locator('[data-kb-output="medium"] input');await result.fill('2100')
   await page.locator('[data-sr-tab="qc"]').click();await expect(page.locator('[data-sr-qc]')).to_be_visible()
   await page.locator('[data-sr-tab="hasil"]').click();assert await result.input_value()=='2100'
   await result.fill('2000')
   await page.locator('[data-sr-tab="bahan"]').click()
   sources=page.locator('[data-sr-source-details]');assert await sources.count()>=1
   await sources.first.locator('summary').first.click()
   entry=page.locator('[data-kb-entry="'+str(mid)+'"]');await entry.wait_for()
   await expect(entry).to_contain_text('60 karung')
   await page.screenshot(path=str(out/f'sumber-{width}.png'),full_page=True)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await entry.get_by_role('button',name='Ubah',exact=True).click()
   editor=page.locator('[data-koreksi-bahan]');await editor.wait_for(state='visible')
   await expect(editor).to_contain_text('Ubah bahan masuk silo')
   assert await page.locator('[data-sr-tab="hasil"]').is_disabled()
   await editor.get_by_role('button',name='Tutup koreksi').click()
   assert await page.locator('[data-sr-tab="hasil"]').is_enabled()
   await page.locator('[data-sr-tab="riwayat"]').click();await expect(page.locator('[data-sr-panel="riwayat"]')).to_contain_text('pertambahan')
   assert not errors,errors
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==before
   # Pemeriksaan dan penyimpanan hasil tetap menempuh API asli.
   await page.locator('[data-sr-tab="hasil"]').click();await result.fill('2100')
   await page.locator('[data-save-output]').click();await page.locator('[data-review]').wait_for()
   await expect(page.locator('[data-review]')).to_contain_text('pertambahan 100 kg')
   await page.get_by_role('button',name='Konfirmasi pencatatan',exact=True).click()
   await page.locator('[data-pesan]').filter(has_text='tercatat').wait_for()
   assert await page.locator('[data-kb-output="medium"] input').input_value()=='2100'
   async with pg() as db:
    values=(await db.scalars(select(PolishingOutputLog.berat_kg))).all();assert sum(values)==2300
   assert not errors,errors;await browser.close()
