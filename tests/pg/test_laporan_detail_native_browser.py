"""Report detail structure, fresh native values, no PDF/read or transaction POST."""
import asyncio
import json
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
from app.web.laporan_detail_kerangka import metadata
pytestmark=pytest.mark.asyncio
DOC={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
CODES=('penggilingan','penyosohan','kemas_ulang')

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
async def test_native_report_document_retains_auth_dates_and_no_fake_summaries(pg,stok_lengkap,role,warehouse):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        for code in CODES:
            response=await client.get('/laporan/'+code,headers=DOC)
            assert response.status_code==200
            doc=BeautifulSoup(response.text,'html.parser');root=doc.select_one('[data-laporan-detail-native]')
            assert root and not doc.select('#laporan-data')
            assert int(root.select_one('tbody td')['colspan'])==len(metadata(code)['kolom'])
            assert not root.select('form[method=post],input[name=_csrf]')
        for suffix in ('?periode=unknown','?periode=khusus','?dari=not-a-date','?periode=khusus&dari=2026-11-24&sampai=2026-11-01'):
            response=await client.get('/laporan/penggilingan'+suffix,headers=DOC)
            assert response.status_code==422 and 'data-laporan-detail-native' not in response.text
        assert await _sidik(pg)==before

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
@pytest.mark.parametrize('width',[390,1280])
async def test_report_catalog_first_click_structure_before_html_and_data(pg,stok_lengkap,role,warehouse,width):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            for code in CODES:
                path='/laporan/'+code
                await page.goto(BASE+'/laporan',wait_until='load')
                await page.wait_for_function("()=>window.PadiKerangkaDokumenUI&&document.getElementById('padi-dokumen-kerangka')")
                entered,release=asyncio.Event(),asyncio.Event();t['gates'][path]=(entered,release)
                try:
                    await page.locator('.lp-pintu[href="'+path+'"]').press('Enter')
                    await asyncio.wait_for(entered.wait(),20)
                    root=page.locator('[data-laporan-detail-native]');await expect(root).to_be_visible()
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    await expect(root.locator('h1')).to_have_count(0)
                    await expect(root.locator('table thead tr').first).to_be_visible() if width>=900 else None
                    assert sum(int(v) for v in await root.locator('table thead tr').first.locator('th').evaluate_all('ns=>ns.map(n=>n.colSpan)'))==len(metadata(code)['kolom'])
                    assert await root.locator('.lp-panel-aksi button:disabled').count()==2
                    await expect(root.locator('select[name=periode]')).to_have_value('bulan_ini')
                    await expect(page.locator('.bar__balik')).to_have_attribute('href','/laporan')
                    release.set();await expect(root).to_have_count(0)
                    await expect(page.locator('[data-laporan-detail]')).to_be_visible()
                    await expect(page.locator('.lp-panel-aksi a.lp-pdf-utama')).to_have_attribute('href',__import__('re').compile('^/laporan-periode/'+code+r'\.pdf'))
                    # Data-dependent Sosoh columns come from its fresh DTO;
                    # true empty still has actual headers + one message row.
                    data=json.loads(await page.locator('#laporan-data').text_content())
                    assert data['kode']==code
                    if not data['rincian']:
                        await expect(page.locator('#lap-isi table thead')).to_have_count(1)
                        await expect(page.locator('#lap-isi table tbody tr')).to_have_count(1)
                finally:release.set()
            assert not t['posts'] and not t['errors'],t
        assert await _sidik(pg)==before

@pytest.mark.parametrize('width',[390,1280])
async def test_report_custom_filter_draft_and_abandoned_get_never_post(pg,stok_lengkap,width):
    async with await _klien(pg,role=P.ADMIN) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/laporan',wait_until='load')
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            t['gates']['/laporan/penggilingan']=(entered,release);t['completed']['/laporan/penggilingan']=done
            try:
                await page.locator('.lp-pintu[href="/laporan/penggilingan"]').click()
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-laporan-detail-native]')
                await root.locator('select[name=periode]').select_option('khusus')
                await root.locator('input[name=dari]').fill('2026-11-01')
                await root.locator('input[name=sampai]').fill('2026-11-24')
                await root.locator('[data-lp-panduan]').click()
                await page.keyboard.press('Escape');release.set();await asyncio.wait_for(done.wait(),20)
                await expect(root.locator('[data-detail-native-status]')).to_contain_text('Pilihan periode berubah')
                await expect(root.locator('input[name=dari]')).to_have_value('2026-11-01')
                await root.locator('.lp-tampilkan').click()
                await expect(page).to_have_url(__import__('re').compile(r'/laporan/penggilingan\?periode=khusus&dari=2026-11-01&sampai=2026-11-24'))
                # Full document uses the same small native framework first.
                await expect(page.locator('[data-laporan-detail]')).to_be_visible()
                assert not t['posts'] and not t['errors'],t
            finally:release.set()
        assert await _sidik(pg)==before
