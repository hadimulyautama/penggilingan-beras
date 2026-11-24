"""Finite native HTML survives monitoring transformations without truncation."""
import asyncio

import pytest
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.web import kerangka_langsung as native


async def parts(values):
    for value in values:
        yield value


async def body(response):
    return b''.join([p.encode() if isinstance(p,str) else p async for p in response.body_iterator])


@pytest.mark.asyncio
@pytest.mark.parametrize('limited_by',['bytes','chunks'])
async def test_oversize_preserves_prefix_current_tail_and_headers(monkeypatch,limited_by):
    values=[b'awal-',b'tengah-',b'akhir']
    monkeypatch.setattr(native,'BATAS_DOKUMEN_NATIVE',8 if limited_by=='bytes' else 100)
    monkeypatch.setattr(native,'BATAS_POTONGAN_NATIVE',1 if limited_by=='chunks' else 100)
    background=BackgroundTask(lambda:None)
    response=StreamingResponse(parts(values),media_type='text/html',background=background)
    response.raw_headers.extend([(b'set-cookie',b'fixture_a=1'),(b'set-cookie',b'fixture_b=2')])
    original_headers=list(response.raw_headers)
    assert await native.baca_native_terbatas(response) is None
    assert await body(response)==b''.join(values)
    assert response.raw_headers==original_headers and response.background is background


@pytest.mark.asyncio
async def test_missing_length_multichunk_native_preserves_monitoring_tail(monkeypatch):
    from app.web import halaman_bertahap
    async def context(*args,**kwargs):return {}
    async def unavailable(*args,**kwargs):return None
    monkeypatch.setattr(halaman_bertahap,'konteks_kerangka',context)
    monkeypatch.setattr(native,'susun_registry',unavailable)
    request=Request({'type':'http','method':'GET','path':'/pekerjaan','headers':[],
                     'state':{'akun':object(),'dokumen_native_kerangka':True}})
    values=[b'<html><body><div data-pindah-konteks="uji">',
            b'<!-- isi-halaman:akhir --></div>',
            b'<script src="/monitoring/aktivitas.js"></script></body></html>']
    response=StreamingResponse(parts(values),media_type='text/html')
    response.raw_headers.extend([(b'set-cookie',b'fixture_a=1'),(b'set-cookie',b'fixture_b=2')])
    assert 'content-length' not in response.headers
    result=await native.lengkapi_dokumen(request,response)
    assert result is response and await body(result)==b''.join(values)
    assert result.headers.getlist('set-cookie')==['fixture_a=1','fixture_b=2']
    assert int(result.headers['content-length'])==sum(map(len,values))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['unmarked','sse','partial','download','encoded','post','redirect'])
async def test_non_native_streams_are_not_consumed(kind):
    state={'akun':object(),'dokumen_native_kerangka':True}
    headers=[];response_headers={};method='GET';status=200;media='text/html'
    if kind=='unmarked':state.pop('dokumen_native_kerangka')
    if kind=='sse':media='text/event-stream'
    if kind=='partial':headers=[(b'x-pindah',b'1')]
    if kind=='download':response_headers['content-disposition']='attachment; filename="fixture.html"'
    if kind=='encoded':response_headers['content-encoding']='gzip'
    if kind=='post':method='POST'
    if kind=='redirect':status=303
    async def forbidden():
        pytest.fail('An unrelated stream must remain untouched')
        yield b''
    request=Request({'type':'http','method':method,'path':'/pekerjaan','headers':headers,'state':state})
    response=StreamingResponse(forbidden(),status_code=status,media_type=media,headers=response_headers)
    iterator=response.body_iterator;original_headers=list(response.raw_headers)
    assert await native.lengkapi_dokumen(request,response) is response
    assert response.body_iterator is iterator and response.raw_headers==original_headers


@pytest.mark.asyncio
async def test_disconnect_is_not_converted_to_success_or_empty_body():
    async def disconnected():
        yield b'native prefix'
        raise asyncio.CancelledError()
    response=StreamingResponse(disconnected(),media_type='text/html')
    with pytest.raises(asyncio.CancelledError):
        await native.baca_native_terbatas(response)


@pytest.mark.asyncio
async def test_repeatable_async_iterable_does_not_restart_after_prefix(monkeypatch):
    class Repeatable:
        def __aiter__(self):
            return parts([b'awal-',b'tengah-',b'akhir'])
    monkeypatch.setattr(native,'BATAS_DOKUMEN_NATIVE',8)
    response=StreamingResponse(Repeatable(),media_type='text/html')
    assert await native.baca_native_terbatas(response) is None
    assert await body(response)==b'awal-tengah-akhir'
