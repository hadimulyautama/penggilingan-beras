"""One Admin390 owner diagnosis: intercepted metadata vs real HTTP navigation.

Product source/gates untouched. Existing native worker/proxy lifecycle is reused;
only safe protocol observation and a native GET barrier are test-local.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup
import pytest
from starlette.requests import Request

from tests.pg.test_konsolidasi_stok import stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark=pytest.mark.asyncio
TARGET='/riwayat-giling'


def safe_gate(request,decision):
    h=request.headers
    return dict(path=request.url.path,
        sec_fetch_present=any(k.startswith('sec-fetch-') for k in h),
        mode_present='sec-fetch-mode' in h,dest_present='sec-fetch-dest' in h,
        mode_navigate=h.get('sec-fetch-mode')=='navigate',
        dest_document=h.get('sec-fetch-dest')=='document',
        x_pindah_present='x-pindah' in h,x_pindah_one=h.get('x-pindah')=='1',
        explicit_present='x-kerangka-halaman' in h,
        explicit_one=h.get('x-kerangka-halaman')=='1',gate_decision=decision)


@pytest.mark.skipif(not (os.getenv('OWNER_BROWSER') in {'chromium','webkit'} and os.getenv('DETAIL_OUT') and os.getenv('PWA_GUARD')), reason='Owner native HTTP fixture required')
async def test_admin390_gate_interception_vs_native_http(pg,stok_lengkap,monkeypatch):
    from playwright.async_api import async_playwright,expect
    from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
    import hmu_tampilan
    import native_runtime
    from native_transport import NativeTransport
    from browser_checks import BrowserChecks
    from app.web import riwayat_daftar_bertahap as family
    out=Path(os.environ['DETAIL_OUT']);source=Path(__file__).parents[2]
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    assert sha==os.environ['RAILWAY_GIT_COMMIT_SHA']
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source)
    sdk=hashlib.sha256((source/'hmu_tampilan/static/pindah.js').read_bytes()).hexdigest()
    pin=dict(source=str(source),git=sha,cap=hmu_tampilan.CAP_ASET,SDK_sha256=sdk)
    pins={'stages':{'baseline':dict(pin),'candidate':dict(pin)}}
    result=dict(status='FAIL',source=sha,pins=pins,asgi_interception=[],native_http=[],product_gate_unchanged=True)
    original=family.memakai_dokumen
    def observed(request):
        answer=original(request)
        if request.url.path==TARGET:result['asgi_interception'].append(safe_gate(request,answer))
        return answer
    monkeypatch.setattr(family,'memakai_dokumen',observed)
    gate_entered,gate_release=asyncio.Event(),asyncio.Event()
    class ObservedTransport(NativeTransport):
        async def __call__(self,scope,receive,send):
            if scope['type']=='http' and scope['path']==TARGET:
                req=Request(scope);result['native_http'].append(safe_gate(req,original(req)))
                if req.headers.get('X-Pindah')=='1':
                    gate_entered.set();await gate_release.wait()
            return await super().__call__(scope,receive,send)
    monkeypatch.setattr(native_runtime,'NativeTransport',ObservedTransport)
    async with await _klien(pg,role='admin') as client:
        result['before']=await _sidik(pg)
        try:
            async with peramban(client,390) as (page,transport):
                await page.goto(BASE+TARGET,wait_until='load')
                result['asgi_dom']=dict(shell_count=await page.locator('[data-riwayat-daftar-native]').count(),
                    core_available=await page.evaluate("typeof window.PADI_BACA_NATIVE?.mount==='function'"),
                    page_errors=list(transport['errors']),get_paths=list(transport['gets']))
                assert result['asgi_interception'], 'No ASGI document-gate observation'
                await page.screenshot(path=str(out/'gate-asgi-admin390.png'),full_page=True)
            async with native_runtime.native_servers(pins,out,result) as (transport,origin):
                transport.stage='candidate'
                async with async_playwright() as pw:
                    browser=await getattr(pw,os.environ['OWNER_BROWSER']).launch(proxy={'server':origin})
                    context=await browser.new_context(viewport={'width':390,'height':900},service_workers='block',reduced_motion='reduce')
                    try:
                        await context.add_cookies([dict(name=c.name,value=c.value,url=origin) for c in client.cookies.jar])
                        page=await context.new_page();watch=BrowserChecks(page,origin)
                        try:
                            response=await page.goto(origin+TARGET,wait_until='load')
                            assert response.status==200
                            await asyncio.wait_for(gate_entered.wait(),20)
                            shell=page.locator('[data-riwayat-daftar-native]')
                            await expect(shell).to_be_visible()
                            await expect(shell.locator('[data-riwayat-native-fields]')).to_be_visible()
                            assert await shell.locator('[data-riwayat-native-fields] dt').count()==7
                            assert set(await shell.locator('[data-riwayat-native-fields] dd').all_text_contents())=={'Belum dibaca'}
                            await expect(shell.locator('[data-riwayat-native-status]')).to_contain_text('Memuat')
                            await page.screenshot(path=str(out/'gate-native-admin390-before-data.png'),full_page=True)
                            result['native_before_data']=dict(shell_visible=True,phone_field_count=7,waiting_sameurl_get=True)
                        finally:gate_release.set()
                        await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0,timeout=25000)
                        assert await page.locator('.rg-kartu').count()>0
                        result['native_after_data']=dict(shell_gone=True,actual_cards_present=True)
                        await watch.drain_finite();result['browser']=watch.verify(transport)
                    finally:
                        gate_release.set();watch.closing=True
                        await context.close();await browser.close()
            initial=[x for x in result['native_http'] if not x['x_pindah_one']]
            hydration=[x for x in result['native_http'] if x['x_pindah_one']]
            assert initial and initial[0]['mode_navigate'] and initial[0]['dest_document'] and initial[0]['gate_decision']
            assert hydration and not hydration[0]['gate_decision']
            result['observed_cause']=('ASGI route interception omitted Sec-Fetch navigation metadata; real native HTTP document gate succeeds.'
                if not result['asgi_interception'][0]['mode_present'] and not result['asgi_interception'][0]['dest_present']
                   and not result['asgi_interception'][0]['gate_decision'] and result['asgi_dom']['shell_count']==0 else
                'Interception metadata differs; inspect recorded protocol before any product change.')
            result['after']=await _sidik(pg)
            result['fingerprints_unchanged']=result['before']==result['after']
            assert result['fingerprints_unchanged'] and result.get('http_cleanup_ok')
            result['status']='PASS'
        finally:
            gate_release.set()
            (out/'gate-protocol-diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')
