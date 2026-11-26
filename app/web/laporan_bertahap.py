"""Presentasi laporan periode; kueri, angka, gerbang dan PDF tetap native."""
from functools import lru_cache
from pathlib import Path
import re
from datetime import date
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError
from app.services.laporan_periode import TAHAP

TUJUAN = {'laporan': '/laporan', **{'laporan-'+k: '/laporan/'+k for k in TAHAP}}


def parameter(request):
    result = {'periode': request.query_params.get('periode', 'bulan_ini')}
    for key in ('dari', 'sampai'):
        try:
            result[key] = TypeAdapter(date | None).validate_python(request.query_params.get(key))
        except ValidationError as error:
            raise RequestValidationError([{**e, 'loc': ('query', key, *e['loc'])} for e in error.errors()]) from error
    return result


def memakai(request, kind):
    from app.web.halaman_bertahap import memakai_kerangka
    q = request.query_params
    return (kind in TUJUAN and len(request.url.query) <= 2000
        and all(k in {'periode', 'dari', 'sampai'} and len(q.getlist(k)) == 1 for k in q)
        and not getattr(request.state, 'menyusun_kerangka_langsung', False)
        and memakai_kerangka(request, kind))


@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    # Gunakan renderer angka/teks yang sama; jangan menyalin rumus laporan.
    native = (root/'hmu_tampilan/static/laporan-periode-detail.js').read_text()
    start, end = '  function aman(s)', '\nconst data=JSON.parse('
    if native.count(start) != 1 or native.count(end) != 1:
        raise ValueError('Renderer laporan native berubah')
    renderer = "(function(){'use strict';" + native[native.index(start):native.index(end)] + 'window.PadiLaporanRenderer={versi:1,tabel};})();'
    result = [('laporan-renderer-native', renderer),
              ('laporan-kerangka.js', (root/'app/web/static/laporan-kerangka.js').read_text()),
              ('halaman-bertahap.js', (root/'app/web/static/halaman-bertahap.js').read_text())]
    if sum(len(c.encode()) for _, c in result) > 196608 or any('</script' in c.lower() for _, c in result):
        raise ValueError('Batas aset laporan tidak sesuai')
    return tuple(result)


async def kerangka(request, akun, kind, *, navigasi=None):
    from app.web.laporan import _daftar, boleh_lihat, PERIODE, _rentang
    from app.web.halaman_bertahap import konteks_kerangka, penanda
    from app.web.laporan_navigasi import siapkan
    from app.web.tampilan import render
    from app.services.laporan_periode import data_laporan
    context = dict(await konteks_kerangka(request, akun) if navigasi is None else navigasi)
    if kind == 'laporan':
        await siapkan(request, context)
        response = render(request, 'laporan.html', daftar=[dict(kode=l.kode, nama=l.nama, arti=l.arti,
            berperiode=l.berperiode, boleh=boleh_lihat(akun.user, l)) for l in _daftar()], periode=PERIODE, **context)
        response.body = response.body.replace(b'<div class="lp-pilihan">', b'<div class="lp-pilihan" data-laporan-catalogue>', 1)
    else:
        kode = kind.removeprefix('laporan-')
        lap = next((l for l in _daftar() if l.kode == 'tahap_'+kode), None)
        if not lap: raise HTTPException(404, 'Laporan tidak dikenal.')
        if not boleh_lihat(akun.user, lap): raise HTTPException(403, 'Laporan ini tidak tersedia untuk peran Anda.')
        values = parameter(request)
        if values['periode'] not in dict(PERIODE): raise HTTPException(422, 'Periode tidak dikenal.')
        awal, akhir = _rentang(**values)
        utama = ('penyosohan', 'penggilingan', 'pengeringan', 'transfer_pk')
        katalog = sorted((l for l in _daftar() if boleh_lihat(akun.user, l)),
            key=lambda l: utama.index(l.kode.removeprefix('tahap_')) if l.kode.removeprefix('tahap_') in utama else len(utama))
        context.update(layar='laporan', MENU_AKTIF='laporan', kembali='/laporan',
            breadcrumb_induk=dict(nama='Laporan periode', alamat='/laporan'), breadcrumb_detail=lap.nama,
            laporan=lap, tahap=kode, periode=PERIODE, periode_aktif=values['periode'],
            dari=values['dari'] or '', sampai=values['sampai'] or '',
            pilihan_laporan=[dict(kode=l.kode.removeprefix('tahap_'), nama=l.nama,
                kelompok='Proses' if l.kode.removeprefix('tahap_') in utama else 'Laporan lainnya') for l in katalog],
            # Hanya label/struktur pure; template tidak menampilkan nilai nol
            # atau keadaan kosong hasil pembacaan yang belum dilakukan.
            blueprint=data_laporan(kode, awal, akhir, []), LP_ASET=aset(),
            SHELL=dict(kind=kind, stamp=penanda(request, akun, kind),
                data_url='/api/halaman-bertahap/'+kind+('?' + request.url.query if request.url.query else '')))
        response = render(request, 'laporan_bertahap.html', **context)
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


async def susun(request, akun, *, navigasi):
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.kerangka_langsung import kemas_frame
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True, 'frame_kerangka_langsung': True}
    frames = {}
    for kind, path in TUJUAN.items():
        native = Request({**request.scope, 'path': path, 'raw_path': path.encode(), 'query_string': b'', 'state': dict(state)})
        response = await kerangka(native, akun, kind, navigasi=navigasi)
        if response.status_code != 200 or len(response.body) > 524288: return None
        frames[path] = response.body.decode()
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
        sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')),
        **kemas_frame(frames))
    return result if len(htmlsafe_json_dumps(result).encode()) <= 1572864 else None
