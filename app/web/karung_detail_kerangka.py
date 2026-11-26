"""Satu kerangka tujuan baca, tanpa membaca saldo atau memanggil writer."""
from functools import lru_cache
from pathlib import Path
from fastapi import Request

PATH = '/stok/karung/detail'


@lru_cache(maxsize=1)
def controller():
    code = (Path(__file__).resolve().parent/'static/karung-detail-kerangka.js').read_text()
    if '</script' in code.lower() or len(code.encode()) > 32768:
        raise ValueError('Batas controller detail karung tidak sesuai')
    return code


async def susun(request, akun, *, navigasi, stok):
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.kerangka_langsung import kemas_frame
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    # Hanya keluarga yang memang tersedia pada shell Stok aktor ini. Ini
    # tidak menggantikan pemeriksaan identitas/lokasi di handler GET native.
    if not stok or 'karung' not in stok['frames']:
        return None
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True,
             'frame_kerangka_langsung': True}
    native = Request({**request.scope, 'path': PATH, 'raw_path': PATH.encode(),
                      'query_string': b'', 'state': state})
    context = dict(navigasi)
    context.update(layar='stok_karung', kembali='/stok?tab=karung',
                   karung_context=penanda_konteks(request, akun), karung_controller=controller())
    response = render(native, 'karung_detail_kerangka.html', **context)
    if response.status_code != 200 or len(response.body) > 524288:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)),
                                      request.cookies.get('produksi_lihat', '')),
                  **kemas_frame({PATH: response.body.decode()}))
    return result if len(htmlsafe_json_dumps(result).encode()) <= 524288 else None
