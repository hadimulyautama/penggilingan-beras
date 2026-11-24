"""Actual native Jasa list provenance and fast same-customer tab navigation."""
import asyncio
import re
import os
from pathlib import Path
import pytest
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.SUPERADMIN,None)])
async def test_five_tabs_current_customer_and_old_get_cannot_replace_new_tab(pg,stok_lengkap,width,role,warehouse):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/jasa',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaJasaDetailUI&&document.getElementById('padi-jasa-detail-catalog')")
            link=page.locator('.jasa-daftar>a.jasa-pelanggan').first
            address=await link.get_attribute('href');path=address.split('?')[0]
            assert re.fullmatch('/jasa/pelanggan/[1-9][0-9]*',path)
            entered,release=asyncio.Event(),asyncio.Event();t['gates'][path]=(entered,release)
            try:
                await link.click();await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-jasa-detail-kerangka]');await expect(root).to_be_visible()
                await expect(root.locator('.jasa-detail-tab a')).to_have_count(5)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert not await root.locator('form[method=post],input[name=_csrf]').count()
                entered2,release2,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
                t['gates'][path]=(entered2,release2);t['completed'][path]=done
                try:
                    await root.locator('.jasa-detail-tab a[href*="tab=proses"]').press('Enter')
                    await asyncio.wait_for(entered2.wait(),20)
                    await expect(page).to_have_url(re.compile(r'/jasa/pelanggan/\d+\?.*tab=proses'))
                    await expect(root.locator('.jasa-detail-tab a[aria-current=page]')).to_contain_text('Proses')
                    release.set()
                    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    await expect(root).to_be_visible()
                    await expect(root.locator('.jasa-detail-tab a[aria-current=page]')).to_contain_text('Proses')
                    folder=os.environ.get('DETAIL_OUT')
                    if folder:await page.screenshot(path=str(Path(folder)/('jasa-native-'+role+'-'+str(width)+'.png')),full_page=True)
                    release2.set();await asyncio.wait_for(done.wait(),20)
                    await expect(root).to_have_count(0)
                    await expect(page.locator('.jasa-detail-tab a[aria-current=page]')).to_contain_text('Proses')
                finally:release2.set()
                assert not t['posts'] and not t['errors'],t
            finally:release.set()
        assert await _sidik(pg)==before

@pytest.mark.parametrize('warehouse',['g1','g2'])
async def test_operator_cannot_gain_jasa_detail_from_route_or_public_program(pg,stok_lengkap,warehouse):
    from bs4 import BeautifulSoup
    async with await _klien(pg,role=P.OPERATOR,gudang_id=stok_lengkap['gudang'][warehouse]) as client:
        before=await _sidik(pg)
        response=await client.get('/jasa/pelanggan/1',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert response.status_code==403
        assert not BeautifulSoup(response.text,'html.parser').select('[data-jasa-detail-kerangka],#padi-jasa-detail-catalog')
        assert await _sidik(pg)==before
