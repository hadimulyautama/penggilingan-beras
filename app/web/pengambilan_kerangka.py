"""Fase baca sebelum editor jasa native; draf dan penerbitan tidak diubah."""
from functools import lru_cache
from pathlib import Path
import re

PATH = '/barang-keluar/pengambilan-jasa'
PROTOTYPE = '__PJ_ID__'

def alamat_kerangka(raw):
    from urllib.parse import urlsplit, parse_qs
    if not isinstance(raw, str) or len(raw) > 4096 or '\\' in raw or any(ord(c) < 32 for c in raw):
        return False
    try:
        u = urlsplit(raw)
        q = parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return False
    pid = q.get('pelanggan_id', [''])[0]
    return bool(not (u.scheme or u.netloc or u.fragment) and u.path == PATH
                and not (set(q)-{'pelanggan_id'}) and all(len(v) == 1 for v in q.values())
                and (not pid or re.fullmatch(r'[1-9]\d{0,9}', pid) and int(pid) <= 2147483647))

async def pembaca(request, akun):
    from app.web.retur_supplier_kerangka import pembaca as internal
    from app.peran import can_see_financials
    return internal(request, akun) and can_see_financials(akun.user)

@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    css = (root/'hmu_tampilan/static/pengambilan-jasa.css').read_text()
    engine = (root/'hmu_tampilan/static/editor-perintah.js').read_text()
    reader = (root/'app/web/static/pengambilan-kerangka.js').read_text()
    if '</style' in css.lower() or re.search(r'@import|url\s*\(', css, re.I) or any('</script' in s.lower() for s in (engine, reader)) or sum(len(s.encode()) for s in (css, engine, reader)) > 98304:
        raise ValueError('Aset pembukaan pengambilan di luar kontrak')
    return dict(css=css, engine=engine, reader=reader)

async def susun(request, akun, *, navigasi):
    from fastapi import Request
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not await pembaca(request, akun):
        return None
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True, 'frame_kerangka_langsung': True}
    native = Request({**request.scope, 'path': PATH, 'raw_path': PATH.encode(), 'query_string': b'', 'state': state})
    context = {**navigasi, 'layar': 'barang_keluar', 'MENU_AKTIF': 'barang_keluar'}
    body = render(native, 'pengambilan_kerangka.html', **context, draf_id=PROTOTYPE,
                  awal=dict(revisi=0, isi=dict(jenis='jasa', pelanggan='')), pengambilan_jasa=True,
                  pj_aset=aset(), pj_context=penanda_konteks(request, akun)).body
    if len(body) > 393216 or b'<script src="/static/editor-perintah.js' in body:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')), html=body.decode())
    return result if len(htmlsafe_json_dumps(result).encode()) <= 524288 else None
