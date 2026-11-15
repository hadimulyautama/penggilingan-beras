"""Navigasi daftar, filter, dan detail melalui template/JS/API fixture asli."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from tests.pg.test_retur_supplier import asal,skema_retur_timbang
from tests.pg.histori_retur_fixture import arsip
from tests.pg.test_riwayat_retur_supplier import sidik_semua
from tests.pg.test_riwayat_giling import _klien

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_HISTORI')!='1',reason='Browser lokal opsional')]


@pytest.mark.parametrize('width',[1440,390,320])
@pytest.mark.parametrize('role',['operator','admin','superadmin'])
async def test_halaman_filter_dan_kembali_tiga_peran(pg,asal,width,role):
    from playwright.async_api import async_playwright,expect
    async with pg() as db:await arsip(db,asal)
    async with await _klien(pg,peran=role,gudang='Gudang 2') as c:
        async with pg() as db:before=await sidik_semua(db)
        async with async_playwright() as pw:
            b=await pw.chromium.launch();page=await b.new_page(viewport=dict(width=width,height=1000),service_workers='block',reduced_motion='reduce')
            errors=[];posts=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.context.add_cookies([dict(name=k.name,value=k.value,url='http://uji') for k in c.cookies.jar])
            async def route(r):
                req=r.request;u=urlsplit(req.url)
                if u.netloc!='uji' or req.resource_type=='eventsource':return await r.abort()
                if req.method!='GET':posts.append(req.method+' '+u.path);return await r.abort()
                response=await c.get(u.path+('?' +u.query if u.query else ''))
                await r.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding')})
            await page.route('**/*',route)
            try:
                path=f'/riwayat-retur-supplier?supplier={asal["sid"]}&gudang={asal["wh"]}&penerimaan={asal["tid"]}'
                await page.goto('http://uji'+path)
                await expect(page.locator('.rsh-tabel tbody tr')).to_have_count(20)
                await expect(page.locator('[aria-label="Rekap seluruh hasil filter"]')).to_contain_text('45')
                next_=page.locator('nav[aria-label="Halaman riwayat"]').get_by_role('link',name='Berikutnya',exact=True)
                await next_.focus();await page.keyboard.press('Enter')
                await expect(page.locator('nav[aria-label="Halaman riwayat"]')).to_contain_text('Halaman 2 dari 3')
                state=page.url
                assert parse_qs(urlsplit(state).query)['penerimaan']==[str(asal['tid'])]
                await page.locator('a[href^="/riwayat-retur-supplier/"]:visible').first.click()
                await page.locator('.rsp-kembali').wait_for()
                await page.locator('.rsp-kembali').click()
                await expect(page).to_have_url(state)
                await page.go_back();await page.locator('.rsp-kembali').wait_for()
                await page.go_forward();await expect(page).to_have_url(state)
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                # Cari menggunakan input biasa (jalur dinamis lama), lalu kembali.
                await page.get_by_role('searchbox').fill('ARSIP')
                await page.locator('#rrs-form button[type="submit"]').first.click()
                await expect(page.locator('[aria-label="Rekap seluruh hasil filter"]')).to_contain_text('44')
                await expect(page.locator('.rsh-tabel tbody tr')).to_have_count(20)
                assert parse_qs(urlsplit(page.url).query)['penerimaan']==[str(asal['tid'])]
                out=os.getenv('BUKTI_HISTORI')
                if out:await page.screenshot(path=str(Path(out)/f'histori-{role}-{width}.png'))
                assert not errors and not posts,(errors,posts)
            finally:await b.close()
        async with pg() as db:assert await sidik_semua(db)==before
