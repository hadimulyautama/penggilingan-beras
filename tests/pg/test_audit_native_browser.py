"""Audit native shell: explicit Admin gate, read filters, no undo POST."""
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
pytestmark=pytest.mark.asyncio
DOC={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}

@pytest.mark.parametrize('role,warehouse,allowed',[(P.ADMIN,None,True),(P.SUPERADMIN,None,True),(P.OPERATOR,'g1',False),(P.OPERATOR,'g2',False)])
async def test_audit_document_and_manifest_use_same_native_admin_gate(pg,stok_lengkap,role,warehouse,allowed):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        home=await client.get('/kabar')
        host=BeautifulSoup(home.text,'html.parser').select_one('#padi-riwayat-kerangka')
        assert host and ('/audit' in json.loads(host.string)['targets']) is allowed
        shell=await client.get('/audit',headers=DOC)
        doc=BeautifulSoup(shell.text,'html.parser')
        if allowed:
            assert shell.status_code==200 and doc.select_one('[data-audit-native]')
            assert len(doc.select('[data-audit-native] thead th'))==4
            assert not doc.select('form[action="/audit/batalkan"],input[name=log_id]')
            native=await client.get('/audit?rentang=semua&cari=EXACT-NO-MATCH-FIXTURE',headers={'X-Pindah':'1'})
            actual=BeautifulSoup(native.text,'html.parser')
            assert native.status_code==200 and not actual.select('[data-audit-native]')
            assert actual.select_one('template[data-audit-empty-table]')
        else:
            assert shell.status_code in (302,303,403) and not doc.select('[data-audit-native]')
        assert await _sidik(pg)==before

@pytest.mark.parametrize('width',[390,1280])
async def test_audit_first_click_dirty_filter_empty_and_abandoned_get(pg,stok_lengkap,width):
    async with await _klien(pg,role=P.ADMIN) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/riwayat-sosoh',wait_until='load')
            entered,release=asyncio.Event(),asyncio.Event();t['gates']['/audit']=(entered,release)
            try:
                await page.locator('[data-tab-riwayat="audit"]').click()
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-audit-native]');await expect(root).to_be_visible()
                await expect(root.locator('thead th')).to_have_count(4)
                await expect(root.locator('tbody tr')).to_have_count(1)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert not await root.locator('form[method=post]').count()
                # Editing a filter then blurring must retain that choice even
                # when an older GET finishes. It never sends a write.
                search=root.locator('input[type=search]');await search.fill('EXACT-NO-MATCH-FIXTURE')
                await search.press('Tab');release.set()
                await expect(root.locator('[data-audit-native-status]')).to_contain_text('Pilihan berubah')
                await expect(search).to_have_value('EXACT-NO-MATCH-FIXTURE')
                await search.press('Enter')
                await expect(page).to_have_url(__import__('re').compile(r'/audit\?.*cari=EXACT-NO-MATCH-FIXTURE'))
                await expect(root).to_have_count(0)
                await expect(page.locator('table.audit-table thead th')).to_have_count(4)
                await expect(page.locator('table.audit-table tbody tr')).to_have_count(1)
                await expect(page.locator('table.audit-table tbody')).to_contain_text('Tidak ada catatan')
                # Start one different read and leave; late data must never
                # restore audit or expose an undo form on the new page.
                entered2,release2,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
                t['gates']['/audit']=(entered2,release2);t['completed']['/audit']=done
                t['gate_headers']['/audit']={'x-pindah':'1'}
                await page.locator('input[type=search]').fill('')
                await page.locator('input[type=search]').press('Enter',no_wait_after=True)
                await asyncio.wait_for(entered2.wait(),20)
                await expect(page.locator('[data-audit-native]')).to_be_visible()
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/barang-masuk"]').click()
                await expect(page).to_have_url(BASE+'/barang-masuk')
                release2.set();await asyncio.wait_for(done.wait(),20)
                await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                await expect(page.locator('[data-audit-native],table.audit-table')).to_have_count(0)
                assert not t['posts'] and not t['errors'],t
            finally:
                release.set()
                if 'release2' in locals():release2.set()
        assert await _sidik(pg)==before
