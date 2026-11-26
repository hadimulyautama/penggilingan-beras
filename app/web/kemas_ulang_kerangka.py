"""Pintu baca Kemas Ulang; pilihan dan editor tetap milik GET/JS native."""
from functools import lru_cache
from pathlib import Path
import re

PATH = '/stok-produk/kemas-ulang'

def alamat_kerangka(raw):
    from urllib.parse import urlsplit, parse_qs
    if not isinstance(raw, str) or len(raw) > 4096 or '\\' in raw or any(ord(c) < 32 for c in raw):
        return False
    try:
        u = urlsplit(raw)
        q = parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return False
    ids = ('sku_id', 'std_id', 'jasa_id')
    return bool(not (u.scheme or u.netloc or u.fragment) and u.path == PATH
                and 'sku_id' in q and not (set(q)-set(ids)-{'kembali_stok'})
                and all(len(v) == 1 for v in q.values())
                and all(re.fullmatch(r'[1-9]\d{0,9}', q[k][0]) and int(q[k][0]) <= 2147483647
                        for k in ids if k in q)
                and ('kembali_stok' not in q or len(q['kembali_stok'][0]) <= 2000))

async def pembaca(request, akun):
    from app.web.retur_supplier_kerangka import pembaca as internal
    from app.web.kemas_ulang import izin
    from fastapi import HTTPException
    if not internal(request, akun):
        return False
    try:
        await izin(akun.user)
    except HTTPException as error:
        if error.status_code == 403:
            return False
        raise
    return True

@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    engine = (root/'hmu_tampilan/static/kemas-ulang.js').read_text()
    reader = (root/'app/web/static/kemas-ulang-kerangka.js').read_text()
    if any('</script' in s.lower() for s in (engine, reader)) or sum(len(s.encode()) for s in (engine, reader)) > 65536:
        raise ValueError('Aset pintu Kemas Ulang di luar kontrak')
    return dict(engine=engine, reader=reader)

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
    body = render(native, 'kemas_ulang_kerangka.html', **{**navigasi, 'layar': 'stok_produk', 'MENU_AKTIF': 'stok_produk'},
                  ku_aset=aset(), ku_context=penanda_konteks(request, akun)).body
    if len(body) > 393216:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')), html=body.decode())
    return result if len(htmlsafe_json_dumps(result).encode()) <= 524288 else None
