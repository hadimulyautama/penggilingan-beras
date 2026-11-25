"""Native equipment hub: same links/chrome before and after the optional read."""
import asyncio
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
pytestmark=pytest.mark.asyncio
PATH='/pengaturan/alat'

@pytest.mark.parametrize('width',[390,1280])
async def test_equipment_hub_direct_document_keeps_three_native_links_and_chrome(pg,stok_lengkap,width):
    async with await _klien(pg,role=P.SUPERADMIN) as client:
        before=await _sidik(pg)
        actual=BeautifulSoup((await client.get(PATH,headers={'X-Pindah':'1'})).text,'html.parser')
        expected=[(a.get('href'),a.get_text(' ',strip=True)) for a in actual.select('#isi-halaman section.kartu a.btn')]
        assert len(expected)==3
        crumb=str(actual.select_one('.desktop-chrome__crumbrow'))
        async with peramban(client,width) as (page,t):
            entered,release=asyncio.Event(),asyncio.Event();t['gates'][PATH]=(entered,release)
            t['gate_headers'][PATH]={'x-pindah':'1','x-kerangka-halaman':'0'}
            try:
                # This legacy hub has no native /pengaturan menu door: that
                # menu links directly to /pengaturan/mesin. Cover the real deep
                # document and its separate fresh GET, not an invented anchor
                # or a claim that this is pre-HTML sidebar navigation.
                await page.goto(BASE+PATH,wait_until='load')
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-pengaturan-alat-kerangka]');await expect(root).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                got=await root.locator('section.kartu a.btn').evaluate_all("ns=>ns.map(n=>[n.getAttribute('href'),n.textContent.trim()])")
                assert got==[list(row) for row in expected]
                pending=BeautifulSoup(await page.locator('.desktop-chrome__crumbrow').evaluate('(n)=>n.outerHTML'),'html.parser')
                assert str(pending.select_one('.desktop-chrome__crumbrow'))==crumb
                assert await page.locator('.bar__balik').get_attribute('href')=='/pengaturan'
                release.set();await expect(root).to_have_count(0)
                got=await page.locator('#isi-halaman section.kartu a.btn').evaluate_all("ns=>ns.map(n=>[n.getAttribute('href'),n.textContent.trim()])")
                assert got==[list(row) for row in expected]
                assert not t['posts'] and not t['errors'],t
            finally:release.set()
        assert await _sidik(pg)==before

@pytest.mark.parametrize('warehouse',['g1','g2'])
async def test_operator_cannot_mint_hub_permission_from_public_asset(pg,stok_lengkap,warehouse):
    async with await _klien(pg,role=P.OPERATOR,gudang_id=stok_lengkap['gudang'][warehouse]) as client:
        before=await _sidik(pg)
        home=BeautifulSoup((await client.get('/pengaturan')).text,'html.parser')
        assert not home.select('#padi-pengaturan-alat-kerangka')
        response=await client.get(PATH,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert response.status_code==403 and 'data-pengaturan-alat-kerangka' not in response.text
        assert await _sidik(pg)==before
