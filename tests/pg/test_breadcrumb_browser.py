"""Halaman asli: rantai server, Kembali, lebar/tinggi latar dan navigasi instan."""
import os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from playwright.async_api import async_playwright,expect
from tests.pg.test_barang_keluar import gudang,_klien
from tests.pg.test_verifikasi_pengiriman import _setup
from tests.pg.test_verifikasi_detail_browser import server
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BREADCRUMB')!='1',reason='Audit desktop lokal opt-in')]

@pytest.mark.parametrize('engine',['chromium','webkit'])
async def test_rantai_kembali_latar_dan_perpindahan(pg,gudang,engine):
 rs,_=await _setup(pg,gudang,5);rid=rs[0].rec.id;code=rs[0].rec.kode
 async with await _klien(pg,gudang['adm'],'crumb-'+engine) as c,server() as host,async_playwright() as pw:
  browser=await getattr(pw,engine).launch()
  try:
   for width in [1440,1024,390]:
    ctx=await browser.new_context(viewport={'width':width,'height':1000},service_workers='block',reduced_motion='reduce');await ctx.add_cookies([dict(name=x.name,value=x.value,url=host) for x in c.cookies.jar]);page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));await page.route('https://**/*',lambda r:r.abort())
    sizes=[]
    for path in ['/','/barang-keluar',f'/barang-keluar/{rid}','/stok','/pekerjaan','/laporan','/pengaturan']:
     r=await page.goto(host+path);assert r and r.status<400,(path,r.status if r else None)
     chrome=page.locator('.desktop-chrome');crumb=page.locator('.desktop-chrome__crumbrow')
     if width<900:await expect(chrome).not_to_be_visible();continue
     await expect(crumb).to_be_visible();labels=await crumb.locator('.nav-rantai>li').all_text_contents();labels=[' '.join(x.replace('›','').split()) for x in labels]
     assert all(a!=b for a,b in zip(labels,labels[1:])),(path,labels)
     assert await crumb.locator('[aria-current=page]').count()==1
     links=crumb.locator('nav a');back=crumb.locator('.desktop-back')
     if await links.count():assert await back.get_attribute('href')==await links.last.get_attribute('href')
     a,b=await crumb.bounding_box(),await chrome.bounding_box();assert abs(a['width']-b['width'])<=1
     sizes.append((path,a['x'],a['width'],a['height']))
     assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width>=900:
     assert len({round(x[1]) for x in sizes})==1 and len({round(x[2]) for x in sizes})==1,sizes
     assert len({round(x[3]) for x in sizes})==1,sizes
     # Tautan memakai PINDAH asli; rantai dimuat ulang bersama halaman.
     await page.goto(host+'/barang-keluar?q=Penerima')
     link=page.locator(f'a[href*="/barang-keluar/{rid}"]').first;await link.click();await page.wait_for_url('**/barang-keluar/'+str(rid)+'**')
     await expect(page.locator('.desktop-breadcrumb [aria-current=page]')).to_have_text(code)
     await expect(page.locator('.desktop-breadcrumb')).not_to_have_attribute('aria-busy','true')
     back=page.locator('.desktop-back');href=await back.get_attribute('href');assert urlsplit(href).path=='/barang-keluar'
     await back.click();await page.wait_for_url('**/barang-keluar?**');assert parse_qs(urlsplit(page.url).query)['q']==['Penerima']
     await expect(page.locator('.desktop-breadcrumb [aria-current=page]')).to_have_text('Barang Keluar')
     await expect(page.locator('.desktop-breadcrumb')).not_to_have_attribute('aria-busy','true')
     await page.wait_for_function("Array.from(document.querySelectorAll('link[rel=stylesheet]')).filter(x=>new URL(x.href).origin===location.origin).every(x=>x.sheet)")
     await page.screenshot(path=f'/bukti/padiflow-{engine}-{width}.png')
    assert not errors,errors
    await ctx.close()
  finally:await browser.close()
