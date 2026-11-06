"""Desktop/ponsel dengan formulir, API dan PostgreSQL asli; tanpa handler tiruan."""
import os
import asyncio
from pathlib import Path
import pytest
from tests.pg.test_detail_pengeringan_tab import dryer_tab,pengeringan,dryer_pabrik
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
@asynccontextmanager
async def browser(c,width):
 from playwright.async_api import async_playwright
 async with async_playwright() as pw:
  b=await pw.chromium.launch();page=await b.new_page(viewport=dict(width=width,height=1000));errors=[];page.on('pageerror',lambda e:errors.append(e.stack))
  await page.context.add_cookies([dict(name=k.name,value=k.value,url='https://uji') for k in c.cookies.jar])
  async def route(r):
   req=r.request
   if urlsplit(req.url).netloc!='uji':await r.abort();return
   # ASGITransport mengumpulkan seluruh body; stream SSE tidak pernah selesai.
   # Browser memakai polling native saat stream ini tidak tersedia.
   if urlsplit(req.url).path=='/api/aliran':await r.abort();return
   headers={k:v for k,v in req.headers.items() if k.lower() not in ('host','cookie','content-length')}
   response=await asyncio.wait_for(c.request(req.method,req.url,headers=headers,content=req.post_data_buffer),timeout=20)
   await r.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','set-cookie')})
  await page.route('**/*',route)
  try:yield page
  finally:
   await b.close()
   assert not errors,errors
from tests.pg.test_form_kadar_air import fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_PENGERINGAN_DESAIN')!='1',reason='Browser lokal opsional')]

@pytest.mark.parametrize('width',[1440,390,320])
async def test_tab_sumber_draf_target_pengukuran_dan_selesai(pg,dryer_tab,width):
 from playwright.async_api import expect
 kode=dryer_tab['kode'];url='https://uji/proses-aktif/pengeringan/'+kode
 out=Path(os.getenv('BUKTI_PENGERINGAN_DESAIN','../bukti'));out.mkdir(parents=True,exist_ok=True)
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);before=await fakta(pg,dryer_tab)
  async with browser(c,width) as page:
   await page.goto(url)
   await page.locator('.dr-redesign').wait_for();assert await page.locator('.dr-tabs [role=tab]').count()==4
   await expect(page.locator('h1')).to_have_text('Pengeringan aktif')
   assert await page.locator('.dr-code').inner_text()==kode
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   assert await page.locator('#tab-ringkasan').evaluate("e=>getComputedStyle(e).backgroundColor")=='rgba(0, 0, 0, 0)'
   await page.locator('#tab-ringkasan').focus();await page.keyboard.press('ArrowRight')
   await expect(page.locator('#tab-bahan')).to_have_attribute('aria-selected','true')
   await expect(page.locator('#panel-bahan')).to_contain_text(dryer_tab['batch'])
   await expect(page.locator('#panel-bahan')).to_contain_text(dryer_tab['tambahan'])
   await expect(page.locator('#panel-bahan')).to_contain_text('TK-DR-TAB')
   await page.screenshot(path=str(out/f'bahan-{width}.png'),full_page=True)
   await page.locator('#tab-pengukuran').click()
   await expect(page.locator('#panel-pengukuran')).to_contain_text('21 catatan')
   await page.locator('#tab-riwayat').click()
   await expect(page.locator('#panel-riwayat')).to_contain_text('Catatan pendinginan')
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   assert await fakta(pg,dryer_tab)==before
   await page.locator('#tab-ringkasan').click()
   if width<=700:await page.locator('.dr-menu>summary').click()
   await expect(page.locator('.dr-redesign')).to_have_attribute('data-desain-siap','1')
   await page.locator('[data-dr-guide]:visible').click();await expect(page.locator('#dr-panduan')).to_be_visible()
   await page.locator('[data-dr-guide-close]').click()
   await page.locator('.dr-actions a[href*="buka=kadar_air"]').click()
   await page.locator('#f_tes').wait_for(state='visible');await page.locator('#f_tes').fill('18.2')
   await page.locator('[data-tambah=tes]').click()
   points=page.locator('[data-ulang-untuk=tes] input');await points.nth(1).fill('19.8')
   await page.locator('#f_indikator').fill('22')
   await page.screenshot(path=str(out/f'ukur-{width}.png'),full_page=True)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await page.locator('[data-buka-aksi=ubah_target]').click()
   await page.locator('#f_target').wait_for(state='visible')
   await page.locator('#kembali-pengukuran').click()
   await page.locator('#f_tes').wait_for(state='visible')
   assert await page.locator('#f_tes').input_value()=='18.2'
   assert await points.nth(1).input_value()=='19.8'
   assert await page.locator('#f_indikator').input_value()=='22'
   await page.locator('#simpan').click()
   await page.locator('#lembar').wait_for(state='hidden');await page.wait_for_load_state('networkidle')
   f=await fakta(pg,dryer_tab);assert len(f['logs'])==len(before['logs'])+1
   assert f['logs'][-1][:6]==(19,22,18.2,19.8,None,None)
   assert f['status']=='proses' and f['target']==13 and f['stok_silo']==0
   await page.locator('.dr-target').first.click()
   await page.locator('#f_target').fill('14')
   await page.locator('#simpan').click();await page.locator('#ya').wait_for(state='visible')
   assert (await fakta(pg,dryer_tab))['target']==13
   await page.locator('#ya').click();await page.locator('#lembar').wait_for(state='hidden');await page.wait_for_load_state('networkidle')
   f2=await fakta(pg,dryer_tab);assert f2['target']==14 and f2['logs']==f['logs']
   await page.locator('.dr-actions a[href*="buka=selesai_pengeringan"]').click()
   await page.locator('#f_kadar_air').wait_for(state='visible')
   assert await page.locator('#f_kadar_air').input_value()==''
   await page.locator('#f_kadar_air').fill('17')
   await page.locator('#simpan').click();await page.locator('#lembar').wait_for(state='hidden');await page.wait_for_load_state('networkidle')
   await expect(page.locator('.pendinginan-detail')).to_be_visible()
   await page.wait_for_load_state('networkidle')
   after=await fakta(pg,dryer_tab);assert after['status']=='selesai' and after['stok_silo']==0
   assert after['logs'][-1][0] is None and after['logs'][-1][1]==17
   await expect(page.locator('.pendinginan-detail')).to_contain_text('19,0%')
