"""Kerangka tujuan tanpa identitas/saldo pelanggan; seluruh data dari GET native."""
from functools import lru_cache
from pathlib import Path
import re

PROTOTYPE = '/jasa/pelanggan/2147483647'

def alamat_kerangka(raw):
    from app.web.jasa_pesanan_bertahap import alamat
    return isinstance(raw, str) and '#' not in raw and alamat(raw)

def pembaca(request, akun):
    from app.web.retur_supplier_kerangka import pembaca as internal
    from app.peran import can_see_financials
    return internal(request, akun) and can_see_financials(akun.user)

@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    css = '\n'.join((root/'hmu_tampilan/static'/name).read_text() for name in ('jasa-pelanggan.css', 'jasa-kontrol.css'))
    engine = (root/'app/web/static/jasa-pesanan-bertahap.js').read_text()
    reader = (root/'app/web/static/jasa-ringkasan-kerangka.js').read_text()
    controls = (root/'hmu_tampilan/static/jasa-kontrol.js').read_text()
    if '</style' in css.lower() or re.search(r'@import|url\s*\(', css, re.I) or any('</script' in s.lower() for s in (engine, reader, controls)) or sum(len(s.encode()) for s in (css, engine, reader, controls)) > 98304:
        raise ValueError('Aset Ringkasan pelanggan di luar kontrak')
    return dict(css=css, engine=engine, reader=reader, controls=controls)

async def susun(request, akun, *, navigasi):
    from fastapi import Request
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from app.services.jasa_pelanggan import STATUS
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not pembaca(request, akun):
        return None
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True, 'frame_kerangka_langsung': True}
    native = Request({**request.scope, 'path': PROTOTYPE, 'raw_path': PROTOTYPE.encode(), 'query_string': b'', 'state': state})
    body = render(native, 'jasa_ringkasan_kerangka.html', **{**navigasi, 'layar': 'jasa', 'MENU_AKTIF': 'jasa'},
                  jd_aset=aset(), jd_context=penanda_konteks(request, akun), PESANAN_STATUS=STATUS).body
    body = re.sub(rb'<button\b[^>]*\bdata-js-cetak\b[^>]*>', lambda m: m[0].replace(b'data-js-cetak', b'disabled aria-describedby="jd-baca-status" data-js-cetak'), body)
    body = re.sub(rb'<script src="/static/jasa-kontrol\.js[^"]*" defer></script>', b'', body)
    if len(body) > 393216:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')), html=body.decode())
    return result if len(htmlsafe_json_dumps(result).encode()) <= 524288 else None
