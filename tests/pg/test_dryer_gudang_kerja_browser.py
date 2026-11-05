"""Ponsel/desktop memakai JS dan endpoint asli pada basis data uji lokal."""
import os
import pytest
from app.models import PurchaseBatch
from tests.pg.test_dryer_gudang_kerja import tempat, batch
from tests.pg.test_operator_ganti_gudang import _orang, _token, _klien
from tests.pg.test_pengeringan_desain_browser import browser

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('UJI_BROWSER_DRYER_GUDANG') != '1', reason='Browser dryer lokal opsional')]


@pytest.mark.parametrize('width', [390, 1440])
async def test_operator_memilih_gudang_dan_menempatkan_dari_pekerjaan(pg, tempat, width):
    from playwright.async_api import expect
    w = tempat
    aid, uid = await _orang(pg, nama='Operator ponsel', role='operator',
                           username='ponsel', gudang_id=w['g2'])
    bid = await batch(pg, w, uid, jasa=True)
    async with _klien(await _token(pg, aid), gudang='g1') as c:
        async with browser(c, width) as page:
            await page.goto('https://uji/pekerjaan?tab=tindakan')
            await expect(page.locator('.pita-samar')).to_contain_text('BEKERJA DI GUDANG 1')
            assert 'gudang utama' not in (await page.locator('body').inner_text()).lower()
            card = page.locator('.antrian-item').filter(has=page.locator(
                'button[data-post="/api/actions/pindah-tumpukan"]')).first
            await card.locator(':scope > summary').click()
            await page.screenshot(path=f'/private/tmp/operator-dryer-{width}.png', full_page=True)
            async with page.expect_response(lambda r: r.url.endswith('/api/actions/pindah-tumpukan')
                                             and r.request.method == 'POST') as sent:
                await card.get_by_role('button', name='Ke Pengering 1').click()
            response = await sent.value
            assert response.status == 200, await response.text()
            await expect(page.locator('#kabar')).to_contain_text('ditempatkan')
            async with pg() as db:
                b = await db.get(PurchaseBatch, bid)
                assert b.status_batch == 'di_dryer' and b.dryer_id == w['dryer']
                assert b.jasa_id == w['jasa'] and b.berat_total_kg == 11243
            await page.locator('.pita-samar a').click()
            await page.locator('select[name=peran]').wait_for(state='visible')
            assert await page.locator('select[name=peran]').input_value() == 'operator:g1'
            assert set(await page.locator('select[name=peran] option').evaluate_all(
                'options => options.map(o => o.value)')) == {'operator:g1', 'operator:g2'}
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
