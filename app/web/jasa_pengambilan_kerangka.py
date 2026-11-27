"""Struktur Pengambilan & retur pelanggan; identitas/catatan hanya dari GET native."""
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs

PROTOTYPE = '/jasa/pelanggan/2147483647?tab=pengambilan'
KEYS = {'tab', 'status', 'cari', 'halaman', 'pesanan_halaman', 'pesanan_cari', 'pesanan_status'}

def alamat_kerangka(raw):
    if not isinstance(raw, str) or len(raw) > 4096 or '#' in raw or '\\' in raw or any(ord(c) < 32 for c in raw):
        return False
    try:
        u = urlsplit(raw)
        q = parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return False
    return bool(not (u.scheme or u.netloc) and re.fullmatch(r'/jasa/pelanggan/[1-9]\d{0,9}', u.path)
                and int(u.path.rsplit('/', 1)[1]) <= 2147483647
                and q.get('tab') == ['pengambilan'] and not (set(q) - KEYS)
                and all(len(v) == 1 and len(v[0]) <= 200 for v in q.values()))

@lru_cache(maxsize=1)
def aset():
    from app.web.jasa_ringkasan_kerangka import aset as sumber
    native = sumber()
    reader = (Path(__file__).resolve().parents[2]/'app/web/static/jasa-pengambilan-kerangka.js').read_text()
    if '</script' in reader.lower() or sum(len(s.encode()) for s in (native['css'], native['controls'], reader)) > 98304:
        raise ValueError('Aset Pengambilan & retur pelanggan di luar kontrak')
    return dict(css=native['css'], controls=native['controls'], reader=reader)

async def susun(request, akun, *, navigasi):
    from fastapi import Request
    from app.web.jasa_ringkasan_kerangka import pembaca
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not pembaca(request, akun):
        return None
    path, _, query = PROTOTYPE.partition('?')
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True, 'frame_kerangka_langsung': True}
    native = Request({**request.scope, 'path': path, 'raw_path': path.encode(), 'query_string': query.encode(), 'state': state})
    body = render(native, 'jasa_pengambilan_kerangka.html', **{**navigasi, 'layar': 'jasa', 'MENU_AKTIF': 'jasa'},
                  jgr_aset=aset(), jgr_context=penanda_konteks(request, akun)).body
    body = re.sub(rb'<button\b[^>]*\bdata-js-cetak\b[^>]*>', lambda m: m[0].replace(b'data-js-cetak', b'disabled aria-describedby="jgr-baca-status" data-js-cetak'), body)
    body = re.sub(rb'<script src="/static/jasa-kontrol\.js[^"]*" defer></script>', b'', body)
    if len(body) > 393216:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')), html=body.decode())
    return result if len(htmlsafe_json_dumps(result).encode()) <= 524288 else None
