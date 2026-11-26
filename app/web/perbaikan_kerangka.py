"""Kerangka pintu perbaikan; kelayakan undo dan formulir hanya dari GET native."""
from functools import lru_cache
from pathlib import Path
import re

PROTOTYPE = '/barang-keluar/2147483647/perbaikan'

def alamat_kerangka(raw):
    from urllib.parse import urlsplit, parse_qs
    if not isinstance(raw, str) or len(raw) > 4096 or '\\' in raw or any(ord(c) < 32 for c in raw):
        return False
    try:
        u = urlsplit(raw)
        q = parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return False
    match = re.fullmatch(r'/barang-keluar/([1-9]\d{0,9})/perbaikan', u.path)
    return bool(not (u.scheme or u.netloc or u.fragment) and match and int(match[1]) <= 2147483647
                and not (set(q)-{'q','status','sejak','sebelum'})
                and all(len(v) == 1 and len(v[0]) <= 200 for v in q.values()))

async def pembaca(request, akun):
    from app.web.retur_supplier_kerangka import pembaca as internal
    from app.peran import can_see_financials
    return internal(request, akun) and can_see_financials(akun.user)

@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]/'app/web/static'
    css = (root/'perbaikan-pengiriman.css').read_text()
    engine = (root/'perbaikan-pengiriman.js').read_text()
    reader = (root/'perbaikan-kerangka.js').read_text()
    if '</style' in css.lower() or re.search(r'@import|url\s*\(', css, re.I) or any('</script' in s.lower() for s in (engine,reader)) or sum(len(s.encode()) for s in (css,engine,reader)) > 65536:
        raise ValueError('Aset pintu perbaikan di luar kontrak')
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
    native = Request({**request.scope, 'path': PROTOTYPE, 'raw_path': PROTOTYPE.encode(), 'query_string': b'', 'state': state})
    context = {**navigasi, 'layar':'barang_keluar', 'MENU_AKTIF':'barang_keluar', 'pp_aset':aset(), 'pp_context':penanda_konteks(request, akun)}
    body = render(native, 'perbaikan_kerangka.html', **context).body
    if len(body) > 393216:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat','')), html=body.decode())
    return result if len(htmlsafe_json_dumps(result).encode()) <= 524288 else None
