"""Native HTML may be streamed by Monitoring; arbitrary streams stay untouched."""
import asyncio
from types import SimpleNamespace

import pytest
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.web import kerangka_langsung as registry

HTML = (b'<!doctype html><html><body><main data-pindah-konteks="fixture">'
        b'<!-- isi-halaman:akhir --></main>'
        b'<script src="/monitoring/aktivitas.js" defer></script></body></html>')


def request(**state):
    return Request({'type':'http','method':'GET','scheme':'http','path':'/kabar',
        'query_string':b'','headers':[(b'host',b'uji')],
        'state':{'akun':SimpleNamespace(id=1),'dokumen_native_kerangka':True,
                 'panjang_html_native_kerangka':len(HTML),**state}})


async def bytes_of(response):
    return b''.join([x.encode() if isinstance(x,str) else x async for x in response.body_iterator])


@pytest.mark.asyncio
async def test_native_monitoring_without_network_length_preserves_everything(monkeypatch):
    from app.web import halaman_bertahap,stok_kerangka_langsung
    async def nav(*args,**kw):return {}
    async def stock(*args,**kw):return None
    data={'versi':2,'konteks':'fixture','cap':'fixture-cap','sesi':'fixture-session',
          **registry.kemas_frame({k:'<h1>Native</h1>' for k in registry.LITERAL})}
    async def frames(*args,**kw):return data
    monkeypatch.setattr(halaman_bertahap,'konteks_kerangka',nav)
    monkeypatch.setattr(stok_kerangka_langsung,'susun',stock)
    monkeypatch.setattr(registry,'susun_registry',frames)
    async def body():
        yield HTML[:71];yield HTML[71:]
    background=BackgroundTask(lambda:None)
    response=StreamingResponse(body(),media_type='text/html',background=background)
    response.raw_headers.extend([(b'set-cookie',b'fixture-a=1'),(b'set-cookie',b'fixture-b=2')])
    assert 'content-length' not in response.headers
    result=await registry.lengkapi_dokumen(request(),response)
    rendered=await bytes_of(result)
    assert result is response and result.background is background
    assert result.headers.getlist('set-cookie')==['fixture-a=1','fixture-b=2']
    assert rendered.count(b'/monitoring/aktivitas.js')==1
    assert rendered.count(b'id="padi-kerangka-langsung"')==1
    assert int(result.headers['content-length'])==len(rendered)
    assert rendered.replace(rendered[rendered.index(b'\n<script type="application/json"'):rendered.rindex(b'</body>')],b'')==HTML


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['no-marker','bad-marker','oversized-marker','encoded','attachment','partial','api','post','not-native'])
async def test_untrusted_or_unrelated_stream_is_never_consumed(monkeypatch,mode):
    calls=[]
    async def body():calls.append('read');yield HTML
    req=request()
    response=StreamingResponse(body(),media_type='text/html')
    if mode=='no-marker':del req.state.panjang_html_native_kerangka
    elif mode=='bad-marker':req.state.panjang_html_native_kerangka=True
    elif mode=='oversized-marker':req.state.panjang_html_native_kerangka=registry.BATAS_DOKUMEN_NATIVE+1
    elif mode=='encoded':response.headers['content-encoding']='gzip'
    elif mode=='attachment':response.headers['content-disposition']='attachment'
    elif mode=='partial':req.scope['headers'].append((b'x-pindah',b'1'))
    elif mode=='api':req.scope['path']='/api/fixture'
    elif mode=='post':req.scope['method']='POST'
    elif mode=='not-native':req.state.dokumen_native_kerangka=False
    # A request header cannot manufacture renderer ownership.
    req.scope['headers'].append((b'panjang-html-native-kerangka',b'128'))
    assert await registry.lengkapi_dokumen(req,response) is response
    assert not calls
    assert await bytes_of(response)==HTML


@pytest.mark.asyncio
async def test_actual_byte_bound_replays_prefix_and_unread_tail(monkeypatch):
    monkeypatch.setattr(registry,'BATAS_DOKUMEN_NATIVE',64)
    pieces=[b'A'*40,'é'*20,b'untouched tail'];reads=[];closed=[]
    async def body():
        try:
            for piece in pieces:reads.append(piece);yield piece
        finally:closed.append(True)
    response=StreamingResponse(body(),media_type='text/html')
    headers=list(response.raw_headers)
    result=await registry.lengkapi_dokumen(request(panjang_html_native_kerangka=40),response)
    assert reads==pieces[:2] and not closed
    assert list(result.raw_headers)==headers
    assert await bytes_of(result)==b'A'*40+('é'*20).encode()+b'untouched tail'
    assert reads==pieces and closed==[True]


@pytest.mark.asyncio
async def test_replay_close_also_closes_original_iterator(monkeypatch):
    monkeypatch.setattr(registry,'BATAS_DOKUMEN_NATIVE',64)
    closed=[]
    async def body():
        try:yield b'A'*80;yield b'unread'
        finally:closed.append(True)
    response=StreamingResponse(body(),media_type='text/html')
    result=await registry.lengkapi_dokumen(request(panjang_html_native_kerangka=40),response)
    await anext(result.body_iterator)
    await result.body_iterator.aclose()
    assert closed==[True]


@pytest.mark.asyncio
@pytest.mark.parametrize('error',[RuntimeError,asyncio.CancelledError])
async def test_stream_failure_or_cancel_is_not_converted_to_success(error):
    async def body():
        yield HTML[:50]
        raise error('synthetic interrupted stream')
    response=StreamingResponse(body(),media_type='text/html')
    with pytest.raises(error):await registry.lengkapi_dokumen(request(),response)
