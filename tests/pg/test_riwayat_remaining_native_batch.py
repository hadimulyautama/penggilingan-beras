"""Remaining five role/width cases in ONE approved native HTTP lifecycle.

Admin390 is already proven by receipt 2212cbf focused02 and is not repeated.
No socket flags, new ports, product changes or shared harness modifications.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from starlette.requests import Request
from starlette.responses import Response

from tests.pg.test_konsolidasi_stok import stok_lengkap,sosoh_jasa
from tests.pg.riwayat_seven_native_http import exercise,PATHS
from tests.pg.test_riwayat_gate_protocol import safe_gate

pytestmark=pytest.mark.asyncio
CASES=(
    ('operator','g1','/riwayat-giling','/riwayat-qc/pk-hasil-giling',390),
    ('operator','g2','/riwayat-sosoh','/riwayat-qc/pk-luar',390),
    ('admin',None,'/riwayat-giling','/riwayat-qc/gabah-basah',1280),
    ('operator','g1','/riwayat-giling','/riwayat-qc/pk-hasil-giling',1280),
    ('operator','g2','/riwayat-sosoh','/riwayat-qc/pk-luar',1280),
)


@pytest.mark.skipif(not (os.getenv('OWNER_BROWSER') in {'chromium','webkit'} and os.getenv('DETAIL_OUT') and os.getenv('PWA_GUARD')), reason='Owner native HTTP fixture required')
async def test_remaining_five_native_http_lifecycle(pg,stok_lengkap,monkeypatch):
    from playwright.async_api import async_playwright
    import hmu_tampilan
    import native_runtime
    from native_transport import NativeTransport
    from app.web import riwayat_daftar_bertahap as family
    source=Path(__file__).parents[2]
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    assert sha==os.environ['RAILWAY_GIT_COMMIT_SHA']
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source)
    pin=dict(source=str(source),git=sha,cap=hmu_tampilan.CAP_ASET,
        SDK_sha256=hashlib.sha256((source/'hmu_tampilan/static/pindah.js').read_bytes()).hexdigest())
    pins=dict(stages={'baseline':dict(pin),'candidate':dict(pin)})
    out=Path(os.environ['DETAIL_OUT']);lifecycle_out=out/'shared-http';lifecycle_out.mkdir()
    result=dict(status='FAIL',source=sha,cases=[],http_lifecycle_count=1,
                admin390_repeated=False,product_unchanged=True)
    shared=dict(state=dict(path=None,gate=None,fail=False),case_result=None)
    class SharedTransport(NativeTransport):
        async def __call__(self,scope,receive,send):
            if scope['type']=='http' and scope['path'] in PATHS:
                req=Request(scope);current=shared['case_result'];state=shared['state']
                if current is not None:current['protocol'].append(safe_gate(req,family.memakai_dokumen(req)))
                if req.headers.get('X-Pindah')=='1' and scope['path']==state['path']:
                    if state['fail']:
                        state['fail']=False
                        if current is not None:current['read_failures_injected_at_fixture_proxy'].append(scope['path'])
                        return await Response('Synthetic fixture read failure',status_code=503)(scope,receive,send)
                    if state['gate']:
                        entered,release=state['gate'];state['gate']=None;entered.set();await release.wait()
            return await super().__call__(scope,receive,send)
    monkeypatch.setattr(native_runtime,'NativeTransport',SharedTransport)
    done=False
    try:
        async with native_runtime.native_servers(pins,lifecycle_out,result) as (transport,origin):
            transport.stage='candidate';shared.update(transport=transport,origin=origin)
            async with async_playwright() as pw:
                browser=await getattr(pw,os.environ['OWNER_BROWSER']).launch(proxy={'server':origin})
                shared['browser']=browser
                try:
                    for role,warehouse,primary,qc,width in CASES:
                        assert (role,width)!=('admin',390)
                        await exercise(pg,stok_lengkap,monkeypatch,role,warehouse,primary,qc,width,shared=shared)
                        file=out/f'native-{role}-{warehouse or "all"}-{width}'/'focused-native-result.json'
                        case=json.loads(file.read_text())
                        assert case['status']=='PASS' and case['fingerprints_unchanged']
                        result['cases'].append(dict(role=role,warehouse=warehouse,width=width,status='PASS',
                            path_results=case['rows'],fingerprints_unchanged=True,retry_get_only=case['retry_get_only'],
                            leave_pending_get_no_stale_replace=case['leave_pending_get_no_stale_replace'],
                            file=str(file),sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
                finally:
                    if shared['state']['gate']:shared['state']['gate'][1].set()
                    await browser.close()
        assert result.get('http_cleanup_ok') and len(result['cases'])==5
        assert not result['rejected_non_GET'] and not result['foreign_http']
        done=True
    finally:
        result['status']='PASS' if done and result.get('http_cleanup_ok') else 'FAIL'
        (out/'remaining-five-native-batch.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result['status']=='PASS'
