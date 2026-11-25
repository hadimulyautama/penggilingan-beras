"""Real loopback wire for the existing owner browser fixture interface.

Ordinary requests still use the owned client's existing request hooks. Native
response bytes are captured before HTTPX decoding. SSE alone calls the actual
app directly, unbuffered, with the browser's actual cookie/HTTP scope.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

import httpx

BASE = 'http://127.0.0.1:59364'
WIRE_KEY = 'flow_owned_native_wire_v1'
COLLECTOR = ContextVar('flow_owned_native_wire_collector', default=None)


@dataclass(frozen=True)
class NativeWire:
    status: int
    headers: tuple
    body: bytes


class ReplayWire(httpx.AsyncByteStream):
    def __init__(self, body):self.body=body
    async def __aiter__(self):yield self.body


def decoded(wire):
    """Decode only for explicit negative-fixture comparison, never normal send."""
    return httpx.Response(wire.status, headers=wire.headers, content=wire.body).content


def replacement_wire(response, native, method, path, headers):
    """Fail closed unless a reviewed existing fixture deliberately substituted."""
    wire=response.extensions.get(WIRE_KEY)
    if isinstance(wire, NativeWire):
        assert any(wire is item for item in native), 'Wire must come from this owned native request'
        unchanged=(response.status_code==wire.status and tuple(response.headers.raw)==wire.headers
                   and response.content==decoded(wire))
        assert unchanged, 'In-place response override has no reviewed fixture provenance'
        return wire, None
    assert native and native[-1].status==200, 'Replacement requires a successful actual native response'
    kind=None
    mime=response.headers.get('content-type','').split(';')[0]
    if response.status_code==503 and mime in ('application/json','text/html'):
        kind='explicit-existing-503'
    elif response.status_code==200 and method=='GET' and path=='/api/keadaan' and mime=='application/json':
        before=json.loads(decoded(native[-1]));after=response.json()
        assert set(before)==set(after) and before.get('n')
        assert after=={**before,'n':str(before['n'])+'.owner-pending-read-signal'}
        kind='explicit-existing-penanda-signal'
    elif response.status_code==200 and method=='GET' and path=='/api/halaman-bertahap/stok' and mime=='application/json':
        # Existing stock negative: change correlation only AFTER the actual
        # authorised native read. Never invent HTML, rows, scope or a success
        # DTO, and never generalise this rule to another JSON reader.
        before=json.loads(decoded(native[-1]));after=response.json()
        assert set(before)=={'stamp','html'}
        assert type(before['stamp']) is str and before['stamp'] and before['stamp']!='fixture-wrong-context'
        assert type(before['html']) is str
        assert after=={**before,'stamp':'fixture-wrong-context'}, 'Unknown stock JSON override is not the declared stamp negative'
        kind='explicit-existing-stock-stamp'
    elif (response.status_code==200 and method=='GET' and mime=='text/html'
            and headers.get('x-pindah')=='1' and headers.get('x-kerangka-halaman')=='0'):
        before=decoded(native[-1])
        expected,count=re.subn(rb'data-pindah-konteks="[^"]+"',b'data-pindah-konteks="owner-stale-context"',before,count=1)
        assert count==1 and response.content==expected, 'Unknown HTML replacement is not a fixture provenance proof'
        kind='explicit-existing-stale-context'
    assert kind, 'Unknown response replacement has no native wire provenance'
    assert not response.headers.get('content-encoding'), 'Negative fixture must declare its actual encoding'
    return NativeWire(response.status_code,tuple(response.headers.raw),response.content),kind


class SharedNativeHTTP:
    def __init__(self, app, client, origin):
        assert origin==BASE
        self.app,self.client,self.origin=app,client,origin
        self.host=urlsplit(origin).netloc.encode()
        self.data=dict(gates={},gate_headers={},pad_html={},posts=[],errors=[],gets=[],
            completed={},corrupt_context=False,fail_asset=False)
        self.requests=[];self.writes=self.data['posts'];self.errors=self.data['errors'];self.foreign=[]
        self.active=set();self.pending=set();self.held=set();self.closing=False
        self.wire_proofs=[];self.faults=[];self.sse=[]
        self.original_base=None;self.transport=None;self.original_handle=None;self.hook=None
        self.own_handle_before=False;self.started=False

    async def start(self):
        assert isinstance(self.client,httpx.AsyncClient)
        transport=self.client._transport_for_url(httpx.URL(BASE))
        assert isinstance(transport,httpx.ASGITransport), 'Never fall back to network/staging transport'
        assert transport.app is self.app, 'Only the existing fixture app is allowed'
        self.transport=transport;self.original_handle=transport.handle_async_request
        self.own_handle_before='handle_async_request' in transport.__dict__
        self.original_base=self.client.base_url
        self.hook=self.capture
        transport.handle_async_request=self.hook
        self.client.base_url=BASE
        self.started=True

    async def capture(self, request):
        response=await self.original_handle(request)
        raw=b''.join([part async for part in response.stream])
        await response.stream.aclose()
        wire=NativeWire(response.status_code,tuple(response.headers.raw),raw)
        response.extensions[WIRE_KEY]=wire
        response.stream=ReplayWire(raw)
        collector=COLLECTOR.get()
        if collector is not None:collector.append(wire)
        return response

    def release(self):
        for _,release in list(self.data['gates'].values()):release.set()
        for release in tuple(self.held):release.set()

    async def restore(self):
        assert not self.pending, 'Do not restore the owned transport while an app request is active'
        if self.started:
            assert self.transport.handle_async_request is self.hook, 'Another owner changed the fixture transport'
            if self.own_handle_before:self.transport.handle_async_request=self.original_handle
            else:del self.transport.handle_async_request
            self.client.base_url=self.original_base
            self.started=False

    def cleanup_metadata(self):
        return dict(actual_HTTP=True, native_SSE_unbuffered=True, EventSource_replaced=False,
            scaffold=False, pending_client_requests=len(self.pending), client_restored=not self.started,
            wire=self.wire_proofs, explicit_existing_faults=self.faults, sse=self.sse)

    async def __call__(self, scope, receive, send):
        from starlette.responses import Response
        assert scope['type']=='http'
        raw=dict(scope['headers'])
        if raw.get(b'host')!=self.host or scope['client'][0]!='127.0.0.1':
            self.foreign.append(dict(path=scope['path'],owned_host=False))
            return await Response(status_code=403)(scope,receive,send)
        task=asyncio.current_task();self.active.add(task)
        headers=httpx.Headers(scope['headers'])
        safe_names={'x-pindah':{'0','1'},'x-kerangka-halaman':{'0','1'},
            'sec-fetch-mode':{'navigate','cors','no-cors','same-origin'},
            'sec-fetch-dest':{'document','empty','script','style','image','font'}}
        safe={k:v if v in safe_names[k] else 'other' for k,v in headers.items() if k in safe_names}
        path=scope['path'];method=scope['method'];query=scope.get('query_string',b'').decode('ascii')
        call=dict(path=path,query_names=sorted({k for k,_ in parse_qsl(query)}),headers=safe,
            navigation_request=headers.get('sec-fetch-mode')=='navigate' and headers.get('sec-fetch-dest') in {'document','empty'} and headers.get('x-pindah')!='1')
        self.requests.append(call)
        gate=None;job=None;token=None
        try:
            if path=='/api/aliran':
                # Real authenticated native stream: no client buffer, message
                # parsing, response substitution, EventSource wrapper or CORS.
                async def stream_send(message):
                    if message['type']=='http.response.start':
                        call['status']=message['status']
                        mime=dict(message['headers']).get(b'content-type',b'').split(b';')[0]
                        self.sse.append(dict(status=message['status'],mime=mime.decode(),native=True))
                    await send(message)
                return await self.app(scope,receive,stream_send)
            if method=='GET':self.data['gets'].append(path)
            else:self.writes.append(path)
            if path=='/static/barang-masuk-pencarian.js' and self.data['fail_asset']:
                self.faults.append(dict(path=path,kind='explicit-existing-asset-503'))
                call['status']=503
                return await Response('Fixture asset unavailable',status_code=503)(scope,receive,send)
            body=[]
            while True:
                message=await receive()
                assert message['type']=='http.request', 'Owned request disconnected before its body completed'
                body.append(message.get('body',b''))
                if not message.get('more_body',False):break
            native=[];token=COLLECTOR.set(native)
            # Keep the relative URL and actual client.request hook API used by
            # existing retry/ambiguous-save/read-phase fixtures.
            job=asyncio.create_task(self.client.request(method,path+('?' +query if query else ''),
                content=b''.join(body) or None,headers=headers))
            self.pending.add(job);self.active.add(job)
            def settled(done):self.pending.discard(done);self.active.discard(done)
            job.add_done_callback(settled)
            response=await asyncio.wait_for(asyncio.shield(job),60)
            wire,fault=replacement_wire(response,native,method,path,headers)
            if fault:self.faults.append(dict(path=path,kind=fault))
            required=self.data['gate_headers'].get(path,{})
            gate=self.data['gates'].pop(path,None) if all(headers.get(k)==v for k,v in required.items()) else None
            if gate:
                self.held.add(gate[1]);gate[0].set();await asyncio.wait_for(gate[1].wait(),30)
            padding=self.data['pad_html'].pop(path,0) if headers.get('x-pindah')=='1' and headers.get('x-kerangka-halaman')=='0' else 0
            changed=bool(padding or path=='/barang-masuk' and self.data['corrupt_context'])
            if changed:
                assert method=='GET' and wire.status==200 and dict(wire.headers).get(b'content-type',b'').startswith(b'text/html')
                content=decoded(wire)
                if padding:
                    assert type(padding) is int and 0<padding<=16*1024*1024
                    assert content.count(b'</body>')==1, 'Padding control requires the actual document body boundary'
                    content=content.replace(b'</body>',b'<!-- synthetic owner size padding -->'+b'x'*padding+b'</body>',1)
                    self.faults.append(dict(path=path,kind='explicit-existing-size-padding'))
                if path=='/barang-masuk' and self.data['corrupt_context']:
                    self.data['corrupt_context']=False
                    content,count=re.subn(rb'data-bm-context="[^"]+"',b'data-bm-context="stale-response"',content,count=1)
                    assert count==1
                    self.faults.append(dict(path=path,kind='explicit-existing-bm-context'))
                h=tuple((k,v) for k,v in wire.headers if k.lower() not in (b'content-encoding',b'content-length',b'transfer-encoding'))
                wire=NativeWire(wire.status,h,content)
            call['status']=wire.status
            self.wire_proofs.append(dict(path=path,status=wire.status,bytes=len(wire.body),
                sha256=hashlib.sha256(wire.body).hexdigest(),native_bytes=not fault and not changed))
            await send(dict(type='http.response.start',status=wire.status,headers=list(wire.headers)))
            await send(dict(type='http.response.body',body=wire.body,more_body=False))
        except asyncio.CancelledError:
            if not self.closing:self.errors.append(dict(path=path,type='CancelledError'))
            raise
        except Exception as error:
            self.errors.append(dict(path=path,type=type(error).__name__))
            raise
        finally:
            if token is not None:COLLECTOR.reset(token)
            self.active.discard(task)
            if gate:
                self.held.discard(gate[1])
                complete=self.data['completed'].get(path)
                if complete:complete.set()
