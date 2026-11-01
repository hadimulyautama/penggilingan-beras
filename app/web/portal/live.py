"""Dorongan HTML baca yang sudah melewati otorisasi portal, tanpa mutasi.

Penanda global hanya dipakai di server untuk menghindari render berulang.
Pelanggan menerima HTML miliknya dan hash HTML itu, bukan nomor audit global.
"""
import asyncio
import hashlib
import json
import hmac
from time import monotonic
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import Request as NativeRequest

from .navigation import READS
from .security import require_customer, key

router = APIRouter(prefix='/pelanggan/live', tags=['portal-pelanggan'])


def identitas(reader):
    return hmac.new(key(), f'{reader.account_id}:{reader.pelanggan_id}'.encode(), hashlib.sha256).hexdigest()


@router.get('/sesi')
async def sesi(reader=Depends(require_customer)):
    return JSONResponse({'identity': identitas(reader)}, headers={'Cache-Control': 'no-store, private', 'Vary': 'Cookie'})


def tujuan(value):
    try:
        parts = urlsplit(value)
    except ValueError:
        raise HTTPException(404, 'Halaman tidak tersedia.') from None
    if (parts.scheme or parts.netloc or parts.fragment or
            not (parts.path == '/pelanggan' or parts.path.startswith('/pelanggan/')) or parts.path.endswith('.pdf')):
        raise HTTPException(404, 'Halaman tidak tersedia.')
    path = parts.path.removeprefix('/pelanggan')
    if path not in ('', '/') and not READS.fullmatch(path):
        raise HTTPException(404, 'Halaman tidak tersedia.')
    return parts.path + ('?' + parts.query if parts.query else '')


async def snapshot(request, halaman, reader):
    from .routes import read
    from .auth import csrf_context
    # Nonce pada HTML clone harus sama dengan cookie respons aslinya.
    csrf_context(request)
    halaman = tujuan(halaman)
    for _ in range(4):
        parts = urlsplit(halaman)
        req = NativeRequest({**request.scope, 'path': parts.path,
            'raw_path': parts.path.encode(), 'query_string': parts.query.encode(),
            'state': dict(request.scope.get('state', {}))})
        path = parts.path.removeprefix('/pelanggan').strip('/') or 'ringkasan'
        response = await read(req, path, reader)
        if response.status_code in (301, 302, 303, 307, 308):
            halaman = tujuan(response.headers['location'])
            continue
        if response.status_code != 200 or 'text/html' not in response.headers.get('content-type', ''):
            raise HTTPException(404, 'Halaman tidak tersedia.')
        html = response.body.decode('utf-8')
        return dict(n=hashlib.sha256(response.body).hexdigest(), html=html, url=halaman, identity=identitas(reader))
    raise HTTPException(409, 'Halaman sedang berubah. Coba lagi.')


@router.get('/keadaan')
async def keadaan(request: Request, halaman: str, reader=Depends(require_customer)):
    return JSONResponse(await snapshot(request, halaman, reader),
        headers={'Cache-Control': 'no-store, private', 'Vary': 'Cookie'})


async def aliran(request, halaman, jeda=2):
    from app.web.api import _penanda
    penanda = None
    terakhir = None
    render_pada = ping_pada = 0
    while not await request.is_disconnected():
        try:
            # Sambungan panjang tidak boleh mempertahankan izin yang dicabut.
            reader = await require_customer(request)
            sekarang = monotonic()
            baru = await _penanda()
            if baru != penanda or sekarang - render_pada >= 30:
                data = await snapshot(request, halaman, reader)
                render_pada = sekarang
                penanda = baru
                if terakhir != data['n']:
                    terakhir = data['n']
                    ping_pada = sekarang
                    yield 'data: ' + json.dumps(data) + '\n\n'
            if sekarang - ping_pada >= 15:
                ping_pada = sekarang
                yield 'data: ' + json.dumps({'n': terakhir}) + '\n\n'
        except HTTPException as exc:
            yield 'data: ' + json.dumps({'akses': False, 'status': exc.status_code}) + '\n\n'
            return
        await asyncio.sleep(jeda)


@router.get('/aliran', include_in_schema=False)
async def stream(request: Request, halaman: str, reader=Depends(require_customer)):
    from .auth import csrf_context
    csrf_context(request)
    halaman = tujuan(halaman)
    return StreamingResponse(aliran(request, halaman), media_type='text/event-stream',
        headers={'Cache-Control': 'no-store, private', 'Vary': 'Cookie', 'X-Accel-Buffering': 'no'})
