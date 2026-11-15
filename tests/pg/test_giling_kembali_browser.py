"""Navigasi baca melalui browser asli; seluruh HTTP hanya ke fixture ASGI."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from tests.pg.test_riwayat_giling import pabrik,_klien
from tests.pg.data_giling_kembali import isi
from tests.pg.test_riwayat_sosoh_desain_browser import browser

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_HISTORI')!='1',reason='Browser fixture opsional')]

@pytest.mark.parametrize('width',[1440,390,320])
@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_kembali_ke_halaman_asal(pg,pabrik,width,peran):
    from playwright.async_api import async_playwright,expect
    await isi(pg,pabrik,65)
    out=Path(os.environ['BUKTI_HISTORI']);baseline=os.getenv('HISTORI_BASELINE')=='1'
    async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
      async with browser(c,width) as page:
        errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)))
        origin=None
        async def route(r):
            u=urlsplit(r.request.url)
            if u.hostname!='127.0.0.1' or r.request.method!='GET' or r.request.resource_type=='eventsource':return await r.abort()
            return await r.continue_()
        def response(r):
            u=urlsplit(r.url)
            if u.path.startswith('/riwayat-giling'):requests.append(dict(path=u.path,query=u.query,status=r.status,bytes=int(r.headers.get('content-length',0))))
        page.on('response',response)
        await page.route('**/*',route)
        try:
            await page.goto('/riwayat-giling')
            origin=urlsplit(page.url).netloc
            for cursor in (36,6):
                await page.get_by_role('link',name='30 sebelumnya').click()
                await expect(page).to_have_url('http://'+origin+'/riwayat-giling?sebelum='+str(cursor))
            await expect(page.locator('a[href^="/riwayat-giling/3"]:visible').filter(has_text='LOT-UJG-00002')).to_have_count(1)
            awal=page.url
            detail=page.locator('a[href^="/riwayat-giling/3"]:visible').filter(has_text='LOT-UJG-00002')
            await detail.focus();await page.keyboard.press('Enter')
            await expect(page.locator('[data-riwayat-giling]')).to_be_visible()
            await page.locator('[data-rhs-tab=bahan]').click()
            await page.locator('.rhs-back').focus();await page.keyboard.press('Enter')
            await page.locator('[data-daftar-riwayat-proses]').wait_for()
            kembali=page.url
            steps=0
            if baseline:
                while parse_qs(urlsplit(page.url).query).get('sebelum')!=['6'] and steps<3:
                    await page.get_by_role('link',name='30 sebelumnya').click();steps+=1
                    await expect(page).to_have_url('http://'+origin+'/riwayat-giling?sebelum='+str(36 if steps==1 else 6))
            evidence=dict(peran=peran,width=width,awal=awal,kembali=kembali,recovery_steps=steps,requests=requests,errors=errors)
            (out/f'{"before" if baseline else "after"}-kembali-{peran}-{width}.json').write_text(json.dumps(evidence,indent=2)+'\n')
            assert parse_qs(urlsplit(kembali).query).get('sebelum')==['6'],evidence
            target=page.locator('a[href^="/riwayat-giling/3"]:visible').filter(has_text='LOT-UJG-00002')
            await expect(target).to_be_visible()
            await expect(target).to_be_focused()
            await expect(target).to_be_in_viewport()
            saved=page.url
            await page.go_back();await expect(page.locator('[data-riwayat-giling]')).to_be_visible()
            await page.go_forward();await expect(page).to_have_url(saved)
            await expect(target).to_be_in_viewport()
            await page.reload();await expect(target).to_be_focused()
            await expect(page).to_have_url(saved)
            assert not errors,errors
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await page.screenshot(path=str(out/f'after-kembali-{peran}-{width}.png'))
        finally:await page.unroute_all(behavior='ignoreErrors')
