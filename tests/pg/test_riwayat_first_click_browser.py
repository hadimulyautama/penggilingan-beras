"""First-click owner tests, distinct from native document-negotiation proof."""
import asyncio
import json
import os
from pathlib import Path

from bs4 import BeautifulSoup
import pytest
from playwright.async_api import expect

from tests.pg.test_konsolidasi_stok import stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE
from app.web.riwayat_daftar_metadata import PROCESS, QC, metadata

pytestmark=pytest.mark.asyncio
PATHS=tuple(PROCESS)+tuple('/riwayat-qc/'+key for key in sorted(QC))


def allowed(warehouse, path):
    if warehouse is None:return True
    return (path in ('/riwayat-sosoh','/riwayat-qc/pk-luar'))==(warehouse=='g2')


@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g1'),('operator','g2')])
async def test_history_publisher_matches_native_scope_and_navigation(pg,stok_lengkap,role,warehouse):
    from app.web.riwayat_kerangka_langsung import valid
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        response=await client.get('/kabar')
        assert response.status_code==200
        document=BeautifulSoup(response.text,'html.parser')
        host=document.select_one('#padi-riwayat-kerangka')
        assert host and not host.find_parent(class_='bingkai')
        data=json.loads(host.string);assert valid(data)
        assert set(data['targets'])=={path for path in PATHS if allowed(warehouse,path)}
        assert not any(key in data for key in ('html','frames','potongan','rows','totals'))
        for path in PATHS:
            native=await client.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            if not allowed(warehouse,path):
                assert native.status_code==403
                continue
            assert native.status_code==200
            fresh=BeautifulSoup(native.text,'html.parser')
            nav=json.loads(fresh.select_one('[data-laporan-kontrol]')['data-tujuan-tab'])
            expected={tab['kunci']:dict(first=tab['href'],allowed=tab['alamat']) for tab in nav if tab['boleh']}
            assert {key:tab for key,tab in data['menu']['tabs'].items() if key!='laporan'}==expected
            assert fresh.select_one('[data-riwayat-daftar-native]')
        assert await _sidik(pg)==before


async def door(page,path,width):
    controls=page.locator('[data-laporan-kontrol]')
    if await controls.count():
        picker=controls.locator('[data-jenis-riwayat]')
        if await picker.count() and await picker.is_visible() and await picker.locator('option[value="'+path+'"]').count():
            await picker.select_option(path);return
        link=controls.locator('a[href="'+path+'"]').first
        if await link.count() and await link.is_visible():
            await link.click();return
    link=page.locator('#laci a[href="'+path+'"]').first
    if width<900 and not await link.is_visible():await page.locator('#buka-laci').click()
    summary=link.locator('xpath=ancestor::details[not(@open)][1]/summary')
    if await summary.count():await summary.click()
    await link.click()


@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g1'),('operator','g2')])
@pytest.mark.parametrize('width',[390,1280])
async def test_history_structure_before_target_html_and_data(pg,stok_lengkap,role,warehouse,width):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,transport):
            observations=[]
            await page.goto(BASE+'/kabar')
            await page.wait_for_function("()=>document.getElementById('padi-riwayat-kerangka')&&window.PINDAH")
            default=await page.evaluate("()=>JSON.parse(document.getElementById('padi-riwayat-kerangka').textContent).menu.default")
            await expect(page.locator('#laci a[data-riwayat-alias-native]')).to_have_attribute('href',default)
            ordered=(default,)+tuple(path for path in PATHS if path!=default)
            for path in ordered:
                if not allowed(warehouse,path):continue
                entered,release=asyncio.Event(),asyncio.Event()
                transport['gates'][path]=entered,release
                before_gets=transport['gets'].count(path)
                try:
                    await page.evaluate("""path=>{
                     window.__historyUiProbe?.observer.disconnect();
                     const p={path,started:performance.now(),ready:null,generic:0};
                     p.observer=new MutationObserver(records=>{
                      for(const r of records)for(const node of r.addedNodes)if(node.nodeType===1&&(node.matches('.halaman-memuat')||node.querySelector('.halaman-memuat')))p.generic++;
                      const root=document.querySelector('[data-riwayat-daftar-native]');
                      if(p.ready===null&&root?.dataset.url===path&&root.getClientRects().length)p.ready=performance.now()-p.started;
                     });
                     p.observer.observe(document.body,{childList:true,subtree:true});
                     window.__historyUiProbe=p;
                    }""",path)
                    await door(page,path,width)
                    await asyncio.wait_for(entered.wait(),20)
                    root=page.locator('[data-riwayat-daftar-native]')
                    await expect(root).to_be_visible()
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    await expect(root).to_have_attribute('data-url',path)
                    assert transport['gets'].count(path)==before_gets+1
                    assert await page.locator('[data-history-ui-style]').count()>0
                    probe=await page.evaluate("()=>({path:__historyUiProbe.path,ui_ms:__historyUiProbe.ready,generic_insertions:__historyUiProbe.generic})")
                    assert probe['ui_ms'] is not None and probe['generic_insertions']==0
                    observations.append(probe)
                    if os.getenv('DETAIL_OUT'):
                        out=Path(os.environ['DETAIL_OUT'])/'first-click';out.mkdir(exist_ok=True)
                        await page.screenshot(path=str(out/(role+'-'+str(warehouse)+'-'+str(width)+'-'+path.strip('/').replace('/','-')+'-pending.png')),full_page=True)
                    for label in metadata(path)['columns']:
                        if label:await expect(root).to_contain_text(label)
                    await expect(page.locator('[data-laporan-kontrol]')).to_be_visible()
                    await expect(page.locator('#laci a.pintu[aria-current=page]')).to_have_count(1)
                    await expect(page.locator('#laci a.pintu[aria-current=page]')).to_have_attribute('href',path)
                    guide=page.locator('[data-lk-buka]').first
                    await guide.focus();await page.keyboard.press('Enter')
                    dialog=page.locator('dialog[open]')
                    await expect(dialog).to_be_visible()
                    release.set()
                    await expect(root).to_have_attribute('data-padi-baca-native-state','waiting-interaction')
                    await expect(dialog).to_be_visible()
                    await page.keyboard.press('Escape')
                    await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0)
                    await expect(page.locator('[data-lk-buka]').first).to_be_focused()
                    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    assert not transport['posts'] and not transport['errors']
                finally:release.set()
            await page.evaluate('()=>window.__historyUiProbe?.observer.disconnect()')
            if os.getenv('DETAIL_OUT'):
                (Path(os.environ['DETAIL_OUT'])/(role+'-'+str(warehouse)+'-'+str(width)+'-first-click.json')).write_text(json.dumps(observations,indent=2)+'\n')
        assert await _sidik(pg)==before
