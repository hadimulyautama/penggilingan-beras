"""Struktur Beranda tanpa angka operasional; isi tetap handler native."""
from functools import lru_cache
from pathlib import Path
import re
from fastapi import Request

def memakai(request):
    from app.web.halaman_bertahap import memakai_kerangka
    from app.web.portal.scope import is_customer_read
    return (not request.url.query and not is_customer_read(request)
            and not getattr(request.state, 'menyusun_kerangka_langsung', False)
            and memakai_kerangka(request, 'beranda'))

@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    result = []
    for name, path, tag in (
        ('beranda-alur.css', 'hmu_tampilan/static/beranda-alur.css', 'style'),
        ('halaman-bertahap.js', 'app/web/static/halaman-bertahap.js', 'script'),
    ):
        code = (root / path).read_text()
        if not code or len(code.encode()) > 196608 or '</'+tag in code.lower():
            raise ValueError('Aset Beranda belum tersedia')
        if tag == 'style' and re.search(r'@import|url\s*\(', code, re.I):
            raise ValueError('Aset Beranda membutuhkan URL tambahan')
        result.append((name, code, tag))
    return tuple(result)

async def kerangka(request, akun, *, navigasi=None):
    from app.web.halaman_bertahap import konteks_kerangka, penanda
    from app.web.layar import GUDANG, MEJA, boleh_lihat_gudang
    from app.services.beranda import sapaan_dan_tanggal
    from app.web.tampilan import render
    view = getattr(request.state, 'view', 'tamu')
    context = dict(await konteks_kerangka(request, akun) if navigasi is None else navigasi)
    greeting, date = sapaan_dan_tanggal(akun.user.nama if akun.user else None)
    context.update(layar='beranda', sapaan=greeting, tanggal_tampil=date,
        semua_gudang=view in MEJA,
        BERANDA_GUDANG=[dict(id=gid, nama=nama, fungsi=fungsi,
            boleh=boleh_lihat_gudang(view, gid)) for gid, nama, fungsi in GUDANG] if view != 'tamu' else [],
        SHELL=dict(stamp=penanda(request, akun, 'beranda'), data_url='/api/halaman-bertahap/beranda'))
    response = render(request, 'beranda_bertahap.html', **context)
    if getattr(request.state, 'frame_kerangka_langsung', False):
        html = response.body.decode()
        for name, code, tag in aset():
            pattern = (r'<link rel="stylesheet" href="/static/'+re.escape(name)+r'\?[^"<>]+">'
                if tag == 'style' else r'<script src="/static/'+re.escape(name)+r'\?[^"<>]+" defer></script>')
            html, count = re.subn(pattern, lambda _: '<'+tag+' data-beranda-aset-native="'+name+'">'+code+'</'+tag+'>', html)
            if count != 1:
                raise ValueError('Referensi aset Beranda tidak tunggal')
        response.body = html.encode()
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    return response

async def susun(request, akun, *, navigasi):
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.kerangka_langsung import kemas_frame
    from app.web import csrf
    from app.web.security import NAMA_COOKIE, baca_token
    from hmu_tampilan import CAP_ASET
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True,
             'frame_kerangka_langsung': True}
    native = Request({**request.scope, 'path': '/', 'raw_path': b'/',
                      'query_string': b'', 'state': state})
    response = await kerangka(native, akun, navigasi=navigasi)
    if response.status_code != 200 or len(response.body) > 524288:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    return dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
        sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')),
        **kemas_frame({'/': response.body.decode()}))
