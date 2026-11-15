"""Operator memakai JS asli; seluruh HTTP dialihkan ke aplikasi fixture."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect

from tests.pg.test_form_selesai_penyosohan import proses, gudang2, fakta
from tests.pg.test_riwayat_giling import _klien

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_PRESISI')!='1',reason='Browser lokal opsional')]


@pytest.mark.parametrize('width',[1440,390,320])
async def test_operator_memperbaiki_presisi_tanpa_kehilangan_draf(pg,proses,width):
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            page=await browser.new_page(viewport=dict(width=width,height=1000),service_workers='block')
            errors=[];writes=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.context.add_cookies([dict(name=k.name,value=k.value,url='http://uji') for k in c.cookies.jar])
            async def route(r):
                request=r.request;u=urlsplit(request.url)
                if u.netloc!='uji':return await r.abort()
                response=await c.request(request.method,u.path+('?' +u.query if u.query else ''),content=request.post_data_buffer,
                    headers={k:v for k,v in request.headers.items() if k.lower() not in ('host','content-length','cookie')})
                if request.method=='POST':writes.append((u.path,response.status_code))
                await r.fulfill(status=response.status_code,body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding')})
            await page.route('**/*',route)
            try:
                await page.goto('http://uji/proses-sosoh/'+proses['kode'])
                await expect(page.locator('[data-sosoh-ringkas]')).to_have_attribute('data-ready','1')
                field=page.locator('[data-kb-output="medium"] input')
                await expect(field).to_have_attribute('step','0.01')
                await expect(page.locator('#hasil')).to_contain_text('Maksimal 2 desimal')
                before=await fakta(pg)
                await field.fill('100.123')
                await page.locator('[data-save-output]').click()
                await expect(page.locator('[data-galat]')).to_contain_text('2 desimal')
                await expect(field).to_have_value('100.123')
                assert await fakta(pg)==before
                assert [(path,status) for path,status in writes if '/hasil/' in path]==[(f'/api/actions/sosoh-ringkas/{proses["kode"]}/hasil/periksa',400)],writes
                assert all(status==400 for _,status in writes),writes
                assert not any('/simpan' in path for path,_ in writes)
                assert not await page.locator('[data-pemulihan]').is_visible()
                out=os.getenv('BUKTI_PRESISI')
                await page.locator('[data-galat]').scroll_into_view_if_needed()
                if out:await page.screenshot(path=str(Path(out)/f'operator-presisi-{width}.png'),full_page=True)
                await field.fill('100.12')
                await page.locator('[data-save-output]').click()
                await expect(page.locator('[data-pesan]')).to_contain_text('Perubahan tercatat')
                await expect(field).to_have_value('100.12')
                assert [status for path,status in writes if '/hasil/' in path]==[400,200,200],writes
                assert not errors,errors
            finally:
                await browser.close()
