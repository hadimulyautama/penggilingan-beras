"""Kerangka netral Muatan; data, izin record dan editor tetap GET native."""
from functools import lru_cache
from pathlib import Path
import re

PATH = '/muatan'
SELESAI = '/selesai-muat'
PROTOTYPE = '2147483647'


def alamat_kerangka(raw):
    """Opt-in presentasi saja; parameter lain tetap melalui handler native."""
    from urllib.parse import urlsplit, parse_qs
    if not isinstance(raw, str) or len(raw) > 4096 or '\\' in raw or any(ord(c) < 32 for c in raw):
        return False
    try:
        u = urlsplit(raw)
        q = parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return False
    match = re.fullmatch(r'/barang-keluar/([1-9]\d{0,9})/(muatan|selesai-muat)', u.path)
    path = '/'+match[2] if match else u.path
    keys = {'perintah', 'kembali_kerja'} | ({'buka'} if path == SELESAI else {'item', 'semua'})
    if (u.scheme or u.netloc or u.fragment or path not in (PATH, SELESAI)
            or set(q) - keys or any(len(v) != 1 for v in q.values())
            or match and 'perintah' in q):
        return False
    for key in ('perintah', 'item'):
        if q.get(key, [''])[0] and not re.fullmatch(r'[1-9]\d{0,9}', q[key][0]):
            return False
        if q.get(key, [''])[0] and int(q[key][0]) > 2147483647:
            return False
    if match and int(match[1]) > 2147483647 or any(q.get(k, [''])[0] not in ('', '0', '1') for k in ('semua', 'buka')):
        return False
    back = q.get('kembali_kerja', [''])[0]
    return not back or (back == '/pekerjaan' or back.startswith('/pekerjaan?')) and not urlsplit(back).fragment


async def pembaca(request, akun):
    from app.web.retur_supplier_kerangka import pembaca as internal
    from app.web.muatan import boleh_catat
    from app.peran import can_see_financials
    return internal(request, akun) and (await boleh_catat(akun.user) or can_see_financials(akun.user))


@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]/'app/web/static'
    css = (root/'muat-ringkas.css').read_text()
    engine = (root/'muat-ringkas.js').read_text()
    controller = (root/'muatan-kerangka.js').read_text()
    if ('</style' in css.lower() or re.search(r'@import|url\s*\(', css, re.I)
            or any('</script' in s.lower() for s in (engine, controller))
            or sum(len(s.encode()) for s in (css, engine, controller)) > 98304):
        raise ValueError('Batas aset Muatan belum sesuai')
    return dict(css=css, engine=engine, controller=controller)


async def susun(request, akun, *, navigasi):
    from fastapi import Request
    from app.web.kerangka_langsung import kemas_frame
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not await pembaca(request, akun):
        return None
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True,
             'frame_kerangka_langsung': True}
    frames = {}
    for path, query in ((path, query) for path in (PATH, SELESAI) for query in ('', 'perintah='+PROTOTYPE)):
        native = Request({**request.scope, 'path': path, 'raw_path': path.encode(),
                          'query_string': query.encode(), 'state': dict(state)})
        context = dict(navigasi)
        context.update(layar='selesai_muatan' if path == SELESAI else 'catat_muatan',
                       MENU_AKTIF='barang_keluar', perintah=None, boleh_catat=False, boleh_selesai=False,
                       item_awal='', semua_awal='', muatan_shell=True, muatan_selesai=path == SELESAI,
                       muatan_context=penanda_konteks(request, akun), muatan_aset=aset())
        body = render(native, 'muatan_kerangka.html', **context).body
        if len(body) > 262144:
            return None
        frames[path+('?' + query if query else '')] = body.decode()
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')),
                  **kemas_frame(frames))
    return result if len(htmlsafe_json_dumps(result).encode()) <= 393216 else None
