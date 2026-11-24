"""No private stock-options in source documents; fresh native reader owns data."""
import asyncio,json
import pytest
from bs4 import BeautifulSoup
from hmu_identitas import peran as P
from playwright.async_api import expect
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse,tabs,owner',[(P.ADMIN,None,{'bahan','produk','karung'},1),(P.OPERATOR,'g1',{'bahan','produk','karung'},0),(P.OPERATOR,None,{'bahan'},0),(P.OPERATOR,'g2',{'bahan','produk','karung'},0)])
async def test_public_manifest_uses_native_stock_flags_without_entity_metadata(pg,stok_lengkap,role,warehouse,tabs,owner):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        doc=BeautifulSoup((await client.get('/pengaturan/akun')).text,'html.parser')
        assert not doc.select('#padi-stok-kerangka')
        ui=json.loads(doc.select_one('#padi-kerangka-ui').string)
        flags=ui['varians']['stok'];assert set(flags)==tabs
        # G1 with an active warehouse can read all three native stock tabs.
        # No-warehouse Operator is the actual negative case, not a G1 guess.
        native=BeautifulSoup((await client.get('/stok?tab=bahan',headers={'X-Pindah':'1'})).text,'html.parser')
        from urllib.parse import urlsplit,parse_qs
        native_tabs={parse_qs(urlsplit(link['href']).query).get('tab',['bahan'])[0]
                     for link in native.select('nav[aria-label="Jenis stok"] a[href]')}
        assert native_tabs==tabs

        assert all(value in {f'stok-{tab}-{mutu}-{owner}' for mutu in (0,1)} for tab,value in flags.items())
        assert all(isinstance(value,str) for value in flags.values())
        assert not set(ui)-{'versi','sumber','konteks','cap','sesi','varians'}
        assert await _sidik(pg)==before

@pytest.mark.parametrize('role,warehouse,tabs',[(P.ADMIN,None,3),(P.OPERATOR,'g1',3),(P.OPERATOR,'g2',3)])
@pytest.mark.parametrize('width',[390,1280])
async def test_stock_first_click_from_account_without_source_entity_options(pg,stok_lengkap,role,warehouse,tabs,width):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/pengaturan/akun',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaUI&&document.getElementById('padi-kerangka-ui')")
            # Contract-only query serialization: opaque target filter IDs are
            # preserved, not authorized or resolved from the source document.
            preserved=await page.evaluate("""()=>{
             const r=JSON.parse(document.getElementById('padi-kerangka-langsung').textContent),base=r.frames['/barang-masuk'].map(i=>r.potongan[i]).join('');
             const value=PadiKerangkaUI.buat('/stok?tab=bahan&pemilik=jasa&gudang=g2&pelanggan_id=123&cari=A%20%26%20B',base,r.konteks,r.cap,r.sesi);
             const doc=new DOMParser().parseFromString(value.html,'text/html');
             return Array.from(doc.querySelectorAll('[data-ui-stock-public] form'),f=>Object.fromEntries(new FormData(f)));
            }""")
            assert len(preserved)==2
            assert all(form['gudang']=='g2' and form['pelanggan_id']=='123' and form['pemilik']=='jasa' and form['cari']=='A & B' for form in preserved)
            html_enter,html_release=asyncio.Event(),asyncio.Event();data_enter,data_release=asyncio.Event(),asyncio.Event()
            t['gates']['/stok']=(html_enter,html_release);t['gates']['/api/halaman-bertahap/stok']=(data_enter,data_release)
            try:
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/stok"]').click();await asyncio.wait_for(data_enter.wait(),20)
                assert not html_enter.is_set()
                root=page.locator('[data-ui-stock-public]');await expect(root).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await expect(root.locator('h1')).to_have_count(0)
                await expect(root.locator('thead th').first).to_be_visible()
                await expect(root.locator('nav[aria-label="Jenis stok"] a[href]')).to_have_count(tabs)
                await expect(root.locator('select[name=gudang]')).to_be_disabled()
                assert await root.locator('select[name=gudang] option:not([value=""])').count()==0
                await expect(root.locator('[data-sk-cetak]').first).to_be_disabled()
                search=root.locator('input[type=search]');await expect(search).to_be_enabled();geometry=await search.bounding_box()
                button=root.locator('[data-sk-buka="sk-filter"]').first;await button.focus();await page.keyboard.press('Enter')
                await expect(root.locator('#sk-filter')).to_be_visible();await page.keyboard.press('Escape');await expect(button).to_be_focused();await button.blur()
                data_release.set();await expect(root).to_have_count(0)
                final=await page.locator('input[type=search]').bounding_box()
                assert all(abs(geometry[k]-final[k])<=2 for k in ('x','y','width','height')),(geometry,final)
                assert not t['posts'] and not t['errors']
            finally:html_release.set();data_release.set()
        assert await _sidik(pg)==before
