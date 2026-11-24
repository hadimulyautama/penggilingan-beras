"""Monitoring active branch retains authorized first-click registries."""
from types import SimpleNamespace
import asyncio

import pytest
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize('role',['operator','admin'])
@pytest.mark.parametrize('enabled',[False,True])
async def test_native_monitoring_keeps_registry_and_session(pg,lengkap,monkeypatch,role,enabled):
    import hmu_identitas.monitoring as monitoring
    from app.web.kerangka_langsung import LITERAL
    import json
    # Isolate the monitoring enablement branch only. Real auth and database
    # namespace resolution are unchanged; no company/binding/grant is created.
    monkeypatch.setattr(monitoring,'RuangData',SimpleNamespace(
        lingkungan=lambda:object() if enabled else None))
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as client:
        before=await _sidik(pg)
        for path in ('/kabar','/pekerjaan','/barang-masuk','/stok'):
            response=await client.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            assert response.status_code==200 and 'no-store' in response.headers['cache-control']
            doc=BeautifulSoup(response.text,'html.parser')
            hosts=doc.select('#padi-kerangka-langsung')
            assert len(hosts)==1 and not hosts[0].find_parent(class_='bingkai')
            assert len(doc.select('script[src^="/monitoring/aktivitas.js"]'))==int(enabled)
            data=json.loads(hosts[0].string)
            assert set(LITERAL).issubset(data['frames'])
            assert data['konteks']==doc.select_one('.bingkai')['data-pindah-konteks']
            assert data['sesi']==doc.select_one('#formulir-sesi')['data-token']
            assert len(doc.select('#padi-stok-kerangka'))==1
            assert int(response.headers['content-length'])==len(response.content)
        assert await _sidik(pg)==before


@pytest.mark.parametrize('role',['operator','admin'])
@pytest.mark.parametrize('width',[390,1280])
async def test_monitoring_first_frames_from_different_native_pages(pg,lengkap,monkeypatch,role,width):
    import hmu_identitas.monitoring as monitoring
    from playwright.async_api import expect
    from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
    monkeypatch.setattr(monitoring,'RuangData',SimpleNamespace(lingkungan=lambda:object()))
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as client:
        before=await _sidik(pg)
        for source,target,kind in [('/kabar','/pekerjaan','pekerjaan'),
                                   ('/kabar','/barang-masuk','barang-masuk'),
                                   ('/kabar','/stok','stok'),
                                   ('/barang-keluar','/pekerjaan','pekerjaan'),
                                   ('/barang-keluar','/barang-masuk','barang-masuk')]:
            async with peramban(client,width) as (page,transport):
                html_entered,html_release=asyncio.Event(),asyncio.Event()
                data_entered,data_release=asyncio.Event(),asyncio.Event()
                transport['gates'][target]=(html_entered,html_release)
                transport['gates']['/api/halaman-bertahap/'+kind]=(data_entered,data_release)
                try:
                    await page.goto(BASE+source,wait_until='load')
                    await expect(page.locator('#padi-kerangka-langsung')).to_have_count(1)
                    await expect(page.locator('script[src^="/monitoring/aktivitas.js"]')).to_have_count(1)
                    await page.evaluate("""()=>{
                      window.__genericTrace={mutation:false,frame:false,running:true};
                      const check=()=>!!document.querySelector('.halaman-memuat');
                      new MutationObserver(()=>{if(__genericTrace.running)__genericTrace.mutation ||= check()}).observe(document.getElementById('isi-halaman'),{subtree:true,childList:true});
                      function frame(){if(!__genericTrace.running)return;__genericTrace.frame ||= check();requestAnimationFrame(frame)}requestAnimationFrame(frame);
                    }""")
                    if width<900:await page.locator('#buka-laci').click()
                    await page.locator('#laci a[href="'+target+'"]').click()
                    await asyncio.wait_for(data_entered.wait(),20)
                    await page.evaluate("()=>new Promise(resolve=>{let n=0;function f(){if(++n>=24)resolve();else requestAnimationFrame(f)}requestAnimationFrame(f)})")
                    trace=await page.evaluate('()=>{__genericTrace.running=false;return __genericTrace}')
                    assert not trace['mutation'] and not trace['frame']
                    assert not html_entered.is_set()
                    root=page.locator('[data-halaman-bertahap][data-kind="'+kind+'"]')
                    await expect(root).to_be_visible()
                    await expect(root.locator('thead th').first).to_be_visible()
                    await expect(root.locator('input[type=search]').first).to_be_enabled()
                    data_release.set()
                    await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
                    assert not transport['posts'] and not transport['errors']
                finally:html_release.set();data_release.set()
        assert await _sidik(pg)==before
