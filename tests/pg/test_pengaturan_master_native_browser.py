"""Master display structure follows native Admin gate; writers untouched."""
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
PATHS=('/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping')

@pytest.mark.parametrize('role,warehouse,allowed',[(P.ADMIN,None,True),(P.SUPERADMIN,None,True),(P.OPERATOR,'g1',False),(P.OPERATOR,'g2',False)])
async def test_direct_master_document_and_private_host_match_native_guard(pg,stok_lengkap,role,warehouse,allowed):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        home=BeautifulSoup((await client.get('/pengaturan')).text,'html.parser')
        assert bool(home.select('#padi-pengaturan-master-kerangka')) is allowed
        for path in PATHS:
            response=await client.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            doc=BeautifulSoup(response.text,'html.parser');root=doc.select_one('[data-pengaturan-master-kerangka]')
            if allowed:
                assert response.status_code==200 and root
                assert not root.select('form,[name],input:not([disabled]),select:not([disabled])')
            else:
                assert response.status_code in (302,303,403) and root is None
        assert await _sidik(pg)==before

@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('role',[P.ADMIN,P.SUPERADMIN])
async def test_master_native_menu_first_click_inert_fields_then_actual_forms(pg,stok_lengkap,width,role):
    async with await _klien(pg,role=role) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            for path in PATHS:
                await page.goto(BASE+'/pengaturan',wait_until='load')
                await page.wait_for_function("()=>window.PadiKerangkaPengaturanMasterUI&&document.getElementById('padi-pengaturan-master-kerangka')")
                entered,release=asyncio.Event(),asyncio.Event();t['gates'][path]=(entered,release)
                try:
                    await page.locator('.pg-pintu[href="'+path+'"]').press('Enter')
                    await asyncio.wait_for(entered.wait(),20)
                    root=page.locator('[data-pengaturan-master-kerangka]');await expect(root).to_be_visible()
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    await root.locator('summary').press('Enter')
                    await expect(root.locator('#pg-master-nama')).to_be_visible()
                    await expect(root.locator('#pg-master-nama')).to_be_disabled()
                    assert not await root.locator('form,[name]').count()
                    await root.locator('h1').click()
                    release.set();await expect(root).to_have_count(0)
                    await expect(page.locator('.spek-beras')).to_be_visible()
                    assert await page.locator('.spek-beras form[method=post]').count()>0
                finally:release.set()
            assert not t['posts'] and not t['errors'],t
        assert await _sidik(pg)==before
