"""Unwired seven-list proposal. Native guards/readers remain authoritative."""
from __future__ import annotations

from app.web.riwayat_daftar_metadata import PROCESS, alamat, keadaan, metadata


async def _boleh(user, path):
    from app.web.api import _is_gabah_operator, _is_g2_operator, _is_jenis_operator
    if path in PROCESS:
        return await _is_jenis_operator(user, PROCESS[path][1])
    kind = path.removeprefix('/riwayat-qc/')
    if kind in ('gabah-basah', 'gabah-kering'):
        return await _is_gabah_operator(user)
    if kind == 'pk-hasil-giling':
        return await _is_jenis_operator(user, 'penggilingan')
    if kind == 'pk-luar':
        return await _is_g2_operator(user)
    return False


async def kerangka(request, akun, konteks):
    from fastapi import HTTPException
    from app.web.portal.scope import is_customer_read

    target = alamat(request.url.path, request.url.query)
    if (target is None or request.method != 'GET' or is_customer_read(request)
            or getattr(request.state, 'portal_scope', None) is not None):
        return None
    # Native positive guard first; no snapshot or compiler decision grants data.
    if not await _boleh(akun.user, request.url.path):
        raise HTTPException(403, 'Riwayat ini tidak tersedia untuk peran Anda.')
    meta = metadata(request.url.path)
    nav = konteks.get('LAPORAN_NAV')
    if (not nav or nav.get('aktif') != meta['family'] or nav.get('jenis') != meta['kind']
            or nav.get('detail') is not False or request.url.path not in nav.get('boleh_alamat', ())):
        return None
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.tampilan import render

    data = dict(konteks, RIWAYAT_META=meta, RIWAYAT_STATE=keadaan('loading'),
                RIWAYAT_URL=target, RIWAYAT_STAMP=penanda_konteks(request, akun) + '|' + target)
    template = 'riwayat_proses_daftar_kerangka.html' if meta['family'] == 'proses' else 'riwayat_qc_daftar_kerangka.html'
    response = render(request, template, **data)
    for attr in (b'data-lk-cetak=""', b'data-rpd-print'):
        response.body = response.body.replace(attr, attr + b' disabled aria-describedby="riwayat-native-cetak-alasan"')
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def memakai_dokumen(request):
    """Negosiasi HTML saja. GET X-Pindah selalu memakai reader native penuh."""
    return (request.method == 'GET' and request.headers.get('X-Pindah') != '1'
            and alamat(request.url.path, request.url.query) is not None
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in {'document', 'empty'}))


async def dokumen(request, akun):
    """Family handler opt-in before heavy read; native sameURL reader untouched."""
    if not memakai_dokumen(request):
        return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request) or getattr(request.state, 'portal_scope', None) is not None:
        return None
    # Guard precedes metadata/nav even if called outside current native caller.
    if not await _boleh(akun.user, request.url.path):
        from fastapi import HTTPException
        raise HTTPException(403, 'Riwayat ini tidak tersedia untuk peran Anda.')
    from app.web.laporan_navigasi import siapkan
    from app.web.halaman_bertahap import konteks_kerangka
    nav = {}
    await siapkan(request, nav)
    context = await konteks_kerangka(request, akun)
    return await kerangka(request, akun, {**context, **nav})
