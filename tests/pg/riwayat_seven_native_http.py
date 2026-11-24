"""Focused owner acceptance through existing native HTTP; no browser interception.

Replaces the navigation acceptance that the ASGI bridge could not represent.
The proxy can hold/fail one GET as an explicit read-failure control; it never
rewrites document metadata, credentials, product HTML or business data.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from bs4 import BeautifulSoup
from starlette.requests import Request
from starlette.responses import Response

from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from app.web.riwayat_daftar_metadata import PROCESS,QC,metadata
from tests.pg.test_riwayat_gate_protocol import safe_gate

PATHS=tuple(PROCESS)+tuple('/riwayat-qc/'+q for q in sorted(QC))


def allowed(role,warehouse,path):
    return role=='admin' or (path in ('/riwayat-sosoh','/riwayat-qc/pk-luar'))==(warehouse=='g2')


@asynccontextmanager
async def _resources(pins,out,result,shared):
    if shared is not None:
        yield shared['transport'],shared['origin'],shared['browser']
        return
    import native_runtime
    from playwright.async_api import async_playwright
    async with native_runtime.native_servers(pins,out,result) as (transport,origin):
        async with async_playwright() as pw:
            browser=await getattr(pw,os.environ['OWNER_BROWSER']).launch(proxy={'server':origin})
            try:yield transport,origin,browser
            finally:await browser.close()


async def exercise(pg,stock,monkeypatch,role,warehouse,primary,qc,width,shared=None):
    if not (os.getenv('OWNER_BROWSER') in {'chromium','webkit'} and os.getenv('DETAIL_OUT') and os.getenv('PWA_GUARD')):
        pytest.skip('Owner native HTTP fixture required; external modules are not CI dependencies')
    from playwright.async_api import expect
    import hmu_tampilan
    import native_runtime
    from native_transport import NativeTransport
    from browser_checks import BrowserChecks
    from app.web import riwayat_daftar_bertahap as family
    source=Path(__file__).parents[2]
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    assert sha==os.environ['RAILWAY_GIT_COMMIT_SHA']
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source)
    cap=hmu_tampilan.CAP_ASET;sdk=hashlib.sha256((source/'hmu_tampilan/static/pindah.js').read_bytes()).hexdigest()
    pin=dict(source=str(source),git=sha,cap=cap,SDK_sha256=sdk)
    pins=dict(stages={'baseline':dict(pin),'candidate':dict(pin)})
    out=Path(os.environ['DETAIL_OUT'])/f'native-{role}-{warehouse or "all"}-{width}';out.mkdir()
    result=dict(status='FAIL',source=sha,role=role,warehouse=warehouse,width=width,
                browser_interception=False,read_failures_injected_at_fixture_proxy=[],rows=[],protocol=[])
    state=shared['state'] if shared is not None else dict(path=None,gate=None,fail=False)
    state.update(path=None,gate=None,fail=False)
    if shared is not None:shared['case_result']=result
    gate_decision=family.memakai_dokumen
    class OwnedTransport(NativeTransport):
        async def __call__(self,scope,receive,send):
            if scope['type']=='http' and scope['path'] in PATHS:
                req=Request(scope);result['protocol'].append(safe_gate(req,gate_decision(req)))
                if req.headers.get('X-Pindah')=='1' and scope['path']==state['path']:
                    if state['fail']:
                        state['fail']=False;result['read_failures_injected_at_fixture_proxy'].append(scope['path'])
                        return await Response('Synthetic fixture read failure',status_code=503)(scope,receive,send)
                    if state['gate']:
                        entered,release=state['gate'];state['gate']=None;entered.set();await release.wait()
            return await super().__call__(scope,receive,send)
    if shared is None:monkeypatch.setattr(native_runtime,'NativeTransport',OwnedTransport)
    async with await _klien(pg,role=role,gudang_id=stock['gudang'].get(warehouse)) as client:
        result['before']=await _sidik(pg)
        done=False
        try:
            async with _resources(pins,out,result,shared) as (transport,origin,browser):
                transport.stage='candidate'
                context=await browser.new_context(viewport={'width':width,'height':900},service_workers='block',reduced_motion='reduce')
                watch=None
                try:
                    await context.add_cookies([dict(name=c.name,value=c.value,url=origin) for c in client.cookies.jar])
                    page=await context.new_page();watch=BrowserChecks(page,origin)
                    for path in PATHS:
                        if not allowed(role,warehouse,path):
                            response=await page.goto(origin+path,wait_until='load')
                            assert response.status==403
                            assert await page.locator('[data-riwayat-daftar-native]').count()==0
                            result['rows'].append(dict(path=path,status='DENY403'))
                            continue
                        native=BeautifulSoup((await client.get(path,headers={'X-Pindah':'1'})).text,'html.parser')
                        expected_stats=[dict(caption=n.find('span').get_text(strip=True),value=n.find('strong').get_text(strip=True)) for n in native.select('.rpd-stats>div')]
                        entered,release=asyncio.Event(),asyncio.Event();state.update(path=path,gate=(entered,release))
                        try:
                            response=await page.goto(origin+path,wait_until='load');assert response.status==200
                            await asyncio.wait_for(entered.wait(),20)
                            shell=page.locator('[data-riwayat-daftar-native]');await expect(shell).to_be_visible()
                            await expect(shell.locator('[data-riwayat-native-status]')).to_contain_text('Memuat')
                            labels=metadata(path)['columns']
                            if path in PROCESS:
                                if width==390:
                                    fields=shell.locator('[data-riwayat-native-fields]');await expect(fields).to_be_visible()
                                    assert await fields.locator('dt').all_text_contents()==labels
                                    assert set(await fields.locator('dd').all_text_contents())=={'Belum dibaca'}
                                else:
                                    headers=shell.locator('.riwayat-desktop-list');await expect(headers).to_be_visible()
                            else:
                                assert await shell.locator('.tabel-standar__kepala>span').count()==6
                            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                            assert await shell.locator('a[href],form,input').count()==0
                            if path==primary:
                                await page.locator('[data-lk-buka=rpd-panduan]').focus();await page.keyboard.press('Enter')
                                await expect(page.locator('#rpd-panduan')).to_be_visible()
                                await page.locator('[data-rpd-guide-close]').click()
                                await page.screenshot(path=str(out/'process-before-data.png'),full_page=True)
                            if path==qc:await page.screenshot(path=str(out/'qc-before-data.png'),full_page=True)
                        finally:release.set()
                        await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0,timeout=25000)
                        if path in PROCESS:
                            actual=await page.locator('.rpd-stats>div').evaluate_all("nodes=>nodes.map(n=>({caption:n.querySelector('span').textContent.trim(),value:n.querySelector('strong').textContent.trim()}))")
                            result.setdefault('native_stat_pairs',[]).append(dict(path=path,expected=expected_stats,actual=actual))
                            assert actual==expected_stats
                        else:
                            assert await page.locator('.tabel-standar__kepala>span').count()==6
                            assert await page.locator('[role=cell][aria-colspan="6"]').count()==1
                        result['rows'].append(dict(path=path,status='PASS',native_stats_equal=True if path in PROCESS else None))

                    state.update(path=qc,gate=None,fail=True)
                    await page.goto(origin+qc,wait_until='load')
                    shell=page.locator('[data-riwayat-daftar-native]')
                    await expect(shell.locator('[data-riwayat-native-status]')).to_contain_text('belum dapat dibaca')
                    await expect(shell.locator('[data-riwayat-native-retry]')).to_be_visible()
                    assert await shell.locator('.tabel-standar__kepala>span').count()==6
                    await shell.locator('[data-riwayat-native-retry]').focus();await page.keyboard.press('Enter')
                    await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0,timeout=25000)
                    assert await page.locator('.tabel-standar__kepala>span').count()==6
                    result['retry_get_only']=True

                    entered,release=asyncio.Event(),asyncio.Event();state.update(path=primary,gate=(entered,release))
                    try:
                        await page.goto(origin+primary,wait_until='load');await asyncio.wait_for(entered.wait(),20)
                        if width<900:await page.locator('#buka-laci').click()
                        await page.locator('#laci a[href="/barang-masuk"]').click()
                    finally:release.set()
                    await expect(page).to_have_url(origin+'/barang-masuk',timeout=25000)
                    await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0)
                    await expect(page.locator('[data-bm-page]')).to_be_visible(timeout=25000)
                    await watch.drain_finite();result['browser']=watch.verify(transport)
                    result['leave_pending_get_no_stale_replace']=True
                finally:
                    if state['gate']:state['gate'][1].set()
                    if watch:watch.closing=True
                    await context.close()
            done=True
        finally:
            result['after']=await _sidik(pg);result['fingerprints_unchanged']=result['before']==result['after']
            result['http_cleanup_pending_shared_lifecycle']=shared is not None
            cleanup_ok=shared is not None or result.get('http_cleanup_ok')
            result['status']='PASS' if done and cleanup_ok and result['fingerprints_unchanged'] else 'FAIL'
            (out/'focused-native-result.json').write_text(json.dumps(result,indent=2)+'\n')
            assert result['status']=='PASS'
