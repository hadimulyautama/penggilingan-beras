"""Pure in-process contracts for the actual-HTTP owner fixture; no socket/DB/browser."""
import ast
import asyncio
import gzip
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest

from tests.pg.native_shared_http import (
    BASE, COLLECTOR, WIRE_KEY, NativeWire, SharedNativeHTTP, decoded, replacement_wire,
)


async def native_read(scope, receive, send):
    raw = gzip.compress(b'<main data-pindah-konteks="fixture-context">Native fixture</main>',mtime=0)
    await send(dict(type='http.response.start',status=200,
        headers=[(b'content-type',b'text/html'),(b'content-encoding',b'gzip'),(b'content-length',str(len(raw)).encode())]))
    await send(dict(type='http.response.body',body=raw,more_body=False))


def scope(path='/read', *, method='GET', headers=()):
    return dict(type='http',http_version='1.1',method=method,path=path,raw_path=path.encode(),
        query_string=b'',scheme='http',server=('127.0.0.1',59364),client=('127.0.0.1',12345),
        headers=[(b'host',b'127.0.0.1:59364'),*headers])


async def empty_body():
    return dict(type='http.request',body=b'',more_body=False)


@pytest.mark.asyncio
async def test_native_capture_replays_original_gzip_wire_before_httpx_decoding_and_restores():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native_read),base_url='http://fixture.invalid') as client:
        original_base=client.base_url
        original_handle=client._transport.handle_async_request
        transport=SharedNativeHTTP(native_read,client,BASE)
        await transport.start()
        native=[];token=COLLECTOR.set(native)
        try:
            response=await client.get('/read')
            wire,kind=replacement_wire(response,native,'GET','/read',{})
            assert kind is None and wire is native[0]
            assert wire.body==gzip.compress(response.content,mtime=0)
            assert dict(wire.headers)[b'content-encoding']==b'gzip'
            assert decoded(wire)==response.content and response.content.startswith(b'<main')
        finally:
            COLLECTOR.reset(token)
            await transport.restore()
        assert client.base_url==original_base and client._transport.handle_async_request==original_handle


@pytest.mark.asyncio
async def test_actual_http_adapter_keeps_client_hook_headers_gate_and_completed_without_wire_rewrite():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native_read),base_url=BASE) as client:
        calls=[];original=client.request
        async def hooked(method,url,**kwargs):
            calls.append((method,url,kwargs['headers'].get('sec-fetch-mode'),kwargs['headers'].get('x-pindah')))
            return await original(method,url,**kwargs)
        client.request=hooked
        transport=SharedNativeHTTP(native_read,client,BASE)
        entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
        transport.data['gates']['/read']=(entered,release)
        transport.data['gate_headers']['/read']={'x-pindah':'1','x-kerangka-halaman':'0'}
        transport.data['completed']['/read']=done
        await transport.start();sent=[];job=None
        async def send(message):sent.append(message)
        try:
            job=asyncio.create_task(transport(scope(headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'0'),(b'sec-fetch-mode',b'same-origin')]),empty_body,send))
            await asyncio.wait_for(entered.wait(),1)
            assert not sent and calls==[('GET','/read','same-origin','1')]
            release.set();await asyncio.wait_for(job,1)
            assert done.is_set() and transport.data['gets']==['/read'] and not transport.errors
            assert sent[0]['status']==200 and dict(sent[0]['headers'])[b'content-encoding']==b'gzip'
            assert sent[1]['body']==gzip.compress(b'<main data-pindah-konteks="fixture-context">Native fixture</main>',mtime=0)
            assert transport.wire_proofs[0]['native_bytes'] is True
        finally:
            release.set()
            if job is not None:await asyncio.wait_for(asyncio.gather(job,return_exceptions=True),1)
            await transport.restore()


@pytest.mark.asyncio
async def test_sse_forwards_actual_scope_and_each_native_chunk_without_client_buffer_or_dto():
    entered,release=asyncio.Event(),asyncio.Event();sent=[];seen=[]
    first=dict(type='http.response.start',status=200,headers=[(b'content-type',b'text/event-stream')])
    chunk=dict(type='http.response.body',body=b': native fixture transport control\n\n',more_body=True)
    last=dict(type='http.response.body',body=b'',more_body=False)
    async def stream_app(original,receive,send):
        seen.append(original)
        await send(first);await send(chunk);entered.set()
        await asyncio.wait_for(release.wait(),1)
        await send(last)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=stream_app),base_url=BASE) as client:
        async def must_not_buffer(*args,**kwargs):raise AssertionError('SSE must not use client.request')
        client.request=must_not_buffer
        transport=SharedNativeHTTP(stream_app,client,BASE)
        original=scope('/api/aliran',headers=[(b'cookie',b'fixture-only')])
        async def send(message):sent.append(message)
        task=asyncio.create_task(transport(original,empty_body,send))
        try:
            await asyncio.wait_for(entered.wait(),1)
            assert seen==[original] and seen[0] is original
            assert sent==[first,chunk] and sent[0] is first and sent[1] is chunk
            assert not task.done() and not transport.data['gets']
            release.set();await asyncio.wait_for(task,1)
            assert sent==[first,chunk,last] and not transport.errors
            assert transport.sse==[dict(status=200,mime='text/event-stream',native=True)]
        finally:
            release.set();await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),1)


def test_unknown_or_foreign_native_wire_and_unproven_response_replacement_fail_closed():
    wire=NativeWire(200,((b'content-type',b'text/html'),),b'<main>native</main>')
    normal=httpx.Response(200,content=wire.body,extensions={WIRE_KEY:wire})
    with pytest.raises(AssertionError):replacement_wire(normal,[],'GET','/read',{})
    normal._content=b'unproven in-place change'
    with pytest.raises(AssertionError):replacement_wire(normal,[wire],'GET','/read',{})
    with pytest.raises(AssertionError):replacement_wire(httpx.Response(503,text='fixture'),[],'GET','/read',{})
    with pytest.raises(AssertionError):replacement_wire(httpx.Response(200,json={'unknown':True}),[wire],'GET','/read',{})
    with pytest.raises(AssertionError):replacement_wire(httpx.Response(403,text='forbidden'),[wire],'GET','/read',{})


def test_known_negative_replacements_require_their_original_native_provenance_and_exact_change():
    before=b'<main data-pindah-konteks="fixture-context">unchanged native</main>'
    native=NativeWire(200,((b'content-type',b'text/html'),),before)
    headers={'x-pindah':'1','x-kerangka-halaman':'0'}
    changed=before.replace(b'fixture-context',b'owner-stale-context')
    wire,kind=replacement_wire(httpx.Response(200,headers={'content-type':'text/html'},content=changed),[native],'GET','/read',headers)
    assert wire.body==changed and kind=='explicit-existing-stale-context'
    with pytest.raises(AssertionError):
        replacement_wire(httpx.Response(200,headers={'content-type':'text/html'},content=changed+b'<p>unknown</p>'),[native],'GET','/read',headers)
    signal=NativeWire(200,((b'content-type',b'application/json'),),b'{"n":"fixture-marker","versi":"fixture-cap"}')
    allowed=httpx.Response(200,json={'n':'fixture-marker.owner-pending-read-signal','versi':'fixture-cap'})
    _,kind=replacement_wire(allowed,[signal],'GET','/api/keadaan',{})
    assert kind=='explicit-existing-penanda-signal'
    with pytest.raises(AssertionError):
        replacement_wire(httpx.Response(200,json={'n':'unproven','versi':'fixture-cap'}),[signal],'GET','/api/keadaan',{})
    _,kind=replacement_wire(httpx.Response(503,json={'detail':'explicit fixture outcome'}),[signal],'POST','/api/actions/gabah-masuk',{})
    assert kind=='explicit-existing-503'


def test_real_http_owner_retains_every_pageerror_and_the_shared_fixture_has_no_sse_scaffold():
    folder=Path(__file__).parent/'pg'
    shared=ast.parse((folder/'test_barang_masuk_bertahap_browser.py').read_text())
    peramban=next(n for n in shared.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='peramban')
    assert any(isinstance(n,ast.keyword) and n.arg=='fixed_port' and ast.literal_eval(n.value)==59364 for n in ast.walk(peramban))
    assert not any(isinstance(n,ast.Call) and ast.unparse(n.func).endswith('fulfill') for n in ast.walk(peramban))
    assert 'SSE_PROTOCOL_COMMENT' not in ast.unparse(shared)
    owner=ast.parse((folder/'native_document_http.py').read_text())
    callbacks=[n.args[1] for n in ast.walk(owner) if isinstance(n,ast.Call)
        and ast.unparse(n.func)=='page.on' and len(n.args)==2 and isinstance(n.args[0],ast.Constant) and n.args[0].value=='pageerror']
    assert len(callbacks)==1
    expected=ast.parse('lambda error: transport.errors.append(str(error))',mode='eval').body
    assert ast.dump(callbacks[0])==ast.dump(expected)
    transport=NS(errors=[])
    callback=eval(compile(ast.Expression(callbacks[0]),'native-http-pageerror','eval'),{'transport':transport})
    callback(RuntimeError('/api/aliran due to access control checks.'));callback(TypeError('different failure'))
    assert transport.errors==['/api/aliran due to access control checks.','different failure']


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['asset','padding','bm-context'])
async def test_existing_explicit_negative_controls_remain_labelled_and_do_not_rewrite_other_reads(fault):
    original=b'<html><body><main data-bm-context="fixture-context">native read</main></body></html>'
    calls=[]
    async def app(scope,receive,send):
        calls.append(scope['path'])
        raw=gzip.compress(original,mtime=0)
        await send(dict(type='http.response.start',status=200,headers=[(b'content-type',b'text/html'),(b'content-encoding',b'gzip'),(b'content-length',str(len(raw)).encode())]))
        await send(dict(type='http.response.body',body=raw,more_body=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE) as client:
        transport=SharedNativeHTTP(app,client,BASE);await transport.start();sent=[]
        path='/static/barang-masuk-pencarian.js' if fault=='asset' else '/barang-masuk'
        if fault=='asset':transport.data['fail_asset']=True
        elif fault=='padding':transport.data['pad_html'][path]=16
        else:transport.data['corrupt_context']=True
        async def send(message):sent.append(message)
        try:
            await transport(scope(path,headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'0')]),empty_body,send)
            if fault=='asset':
                assert sent[0]['status']==503 and not calls
            else:
                assert sent[0]['status']==200 and calls==[path]
                assert b'content-encoding' not in dict(sent[0]['headers'])
                if fault=='padding':assert sent[1]['body']==original.replace(b'</body>',b'<!-- synthetic owner size padding -->'+b'x'*16+b'</body>')
                else:assert sent[1]['body']==original.replace(b'fixture-context',b'stale-response')
                assert transport.wire_proofs[0]['native_bytes'] is False
            assert len(transport.faults)==1 and not transport.errors
        finally:await transport.restore()


@pytest.mark.asyncio
async def test_existing_after_commit_opaque_hook_is_sent_once_and_never_replayed_by_adapter():
    calls=[]
    async def app(scope,receive,send):
        calls.append(scope['method'])
        await send(dict(type='http.response.start',status=200,headers=[(b'content-type',b'application/json')]))
        await send(dict(type='http.response.body',body=b'{"ok":true}',more_body=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE) as client:
        original=client.request
        async def opaque(method,url,**kw):
            response=await original(method,url,**kw)
            assert response.status_code==200
            return httpx.Response(503,json={'detail':'explicit existing opaque outcome'})
        client.request=opaque
        transport=SharedNativeHTTP(app,client,BASE);await transport.start();sent=[]
        async def send(message):sent.append(message)
        try:
            await transport(scope('/api/actions/gabah-masuk',method='POST'),empty_body,send)
            assert calls==['POST'] and transport.writes==['/api/actions/gabah-masuk']
            assert sent[0]['status']==503 and len(transport.faults)==1
            assert transport.faults[0]['kind']=='explicit-existing-503' and not transport.errors
        finally:await transport.restore()


class _SessionPage:
    def __init__(self): self.main_frame=object();self.callbacks={}
    def on(self,event,callback): self.callbacks.setdefault(event,[]).append(callback)
    def remove_listener(self,event,callback): self.callbacks[event].remove(callback)
    def emit(self,event,value):
        for callback in list(self.callbacks.get(event,[])): callback(value)


def _session_request(page):
    return NS(url=BASE+'/api/sesi-formulir',method='GET',frame=page.main_frame)


def _session_response(request, *, status=200, mime='application/json'):
    return NS(request=request,status=status,headers={'content-type':mime})


@pytest.mark.asyncio
async def test_stock_setup_drain_freezes_issued_reads_and_preserves_other_listeners():
    from tests.pg.stock_setup_session import stock_setup_sessions,before_stock_setup_goto
    page=_SessionPage();raw=[];page.on('pageerror',raw.append)
    # SimpleNamespace is unhashable; real Playwright Request objects are keys.
    first,late=(type('Request',(),vars(_session_request(page)))() for _ in range(2))
    with stock_setup_sessions(page,BASE) as owner:
        page.emit('request',first)
        drain=asyncio.create_task(before_stock_setup_goto(page));observed=[]
        def finish_after_capture():
            observed.append(not drain.done())
            page.emit('request',late)
            page.emit('response',_session_response(first))
            page.emit('requestfinished',first)
        asyncio.get_running_loop().call_soon(finish_after_capture)
        await drain
        assert observed==[True] and owner.barriers==[dict(issued=1,captured=[1],completed=True)]
        assert owner.rows[late]['terminal'] is None
        page.emit('pageerror','unchanged raw error')
    assert raw==['unchanged raw error'] and page.callbacks['pageerror']==[raw.append]
    assert all(not page.callbacks[event] for event in ('request','response','requestfinished','requestfailed'))
    with pytest.raises(AssertionError): await before_stock_setup_goto(page)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['failed','status','mime','timeout','wrong-frame','wrong-method'])
async def test_stock_setup_drain_rejects_failed_unknown_and_unfinished_session_reads(fault):
    from tests.pg.stock_setup_session import stock_setup_sessions
    page=_SessionPage();request=type('Request',(),vars(_session_request(page)))()
    if fault=='wrong-frame': request.frame=object()
    if fault=='wrong-method': request.method='POST'
    with stock_setup_sessions(page,BASE) as owner:
        page.emit('request',request)
        if fault in ('wrong-frame','wrong-method'):
            with pytest.raises(AssertionError): await owner.drain_issued()
            return
        if fault=='timeout':
            with pytest.raises(asyncio.TimeoutError): await owner.drain_issued(timeout=.001)
            return
        drain=asyncio.create_task(owner.drain_issued())
        def complete():
            page.emit('response',_session_response(request,status=503 if fault=='status' else 200,
                mime='text/html' if fault=='mime' else 'application/json'))
            page.emit('requestfailed' if fault=='failed' else 'requestfinished',request)
        asyncio.get_running_loop().call_soon(complete)
        with pytest.raises(AssertionError): await drain


@pytest.mark.parametrize('fault',['no-native','native-denied','wrong-path','wrong-method','wrong-mime','changed-html','extra-field','different-stamp','native-already-wrong'])
def test_stock_stamp_negative_rejects_anything_outside_exact_authorised_native_envelope(fault):
    import json
    payload={'stamp':'native-fixture-context','html':'<main>Native fixture structure</main>'}
    source_status=403 if fault=='native-denied' else 200
    if fault=='native-already-wrong':payload['stamp']='fixture-wrong-context'
    native=NativeWire(source_status,((b'content-type',b'application/json'),),json.dumps(payload).encode())
    changed={**payload,'stamp':'fixture-wrong-context'}
    if fault=='changed-html':changed['html']='<main>Unproven replacement</main>'
    if fault=='extra-field':changed['extra']='unproven'
    if fault=='different-stamp':changed['stamp']='another-fault'
    mime='text/plain' if fault=='wrong-mime' else 'application/json'
    response=httpx.Response(200,json=changed,headers={'content-type':mime})
    with pytest.raises(AssertionError):
        replacement_wire(response,[] if fault=='no-native' else [native],
            'POST' if fault=='wrong-method' else 'GET',
            '/api/halaman-bertahap/pekerjaan' if fault=='wrong-path' else '/api/halaman-bertahap/stok',{})


@pytest.mark.asyncio
async def test_stock_fault_hook_reads_native_once_before_503_stamp_negative_and_successful_retry():
    import json
    path='/api/halaman-bertahap/stok'
    payload={'stamp':'native-fixture-context','html':'<main>Native fixture structure</main>'}
    reads=[]
    async def app(scope,receive,send):
        reads.append(scope['path'])
        await send(dict(type='http.response.start',status=200,headers=[(b'content-type',b'application/json')]))
        await send(dict(type='http.response.body',body=json.dumps(payload).encode(),more_body=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE) as client:
        original=client.request;faults=iter(('503','stamp','native'))
        async def hook(method,url,**kw):
            response=await original(method,url,**kw)
            assert response.status_code==200
            mode=next(faults)
            if mode=='503':return httpx.Response(503,json={'detail':'Fixture read unavailable'},request=response.request)
            if mode=='stamp':return httpx.Response(200,json={**response.json(),'stamp':'fixture-wrong-context'},request=response.request)
            return response
        client.request=hook
        transport=SharedNativeHTTP(app,client,BASE);await transport.start();sent=[]
        async def send(message):sent.append(message)
        try:
            for _ in range(3):await transport(scope(path),empty_body,send)
            assert reads==[path]*3 and transport.data['gets']==[path]*3
            assert [entry['kind'] for entry in transport.faults]==['explicit-existing-503','explicit-existing-stock-stamp']
            starts=[message['status'] for message in sent if message['type']=='http.response.start']
            assert starts==[503,200,200] and not transport.writes and not transport.errors
            assert [entry['native_bytes'] for entry in transport.wire_proofs]==[False,False,True]
        finally:await transport.restore()
