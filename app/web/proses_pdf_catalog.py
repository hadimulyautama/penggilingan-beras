"""Private report-link proof from native authorized detail DTO, never SQL."""
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from app.web.giling_work_catalog import _visible
from app.web.proses_pdf_kerangka import deskripsi, valid_meta

HOST = 'padi-proses-pdf-catalog'


@lru_cache(maxsize=1)
def aset():
    folder = Path(__file__).parent / 'static'
    meta = json.loads((folder / 'kerangka-proses-pdf-ui.meta.json').read_text())
    if (meta.get('versi') != 1 or meta.get('variants') != ['giling', 'sosoh', 'pengeringan']
            or hashlib.sha256((folder / 'kerangka-proses-pdf-ui.js').read_bytes()).hexdigest() != meta.get('aset_sha256')):
        raise ValueError('Process PDF viewer package mismatch')
    return meta


def susun_data(source, body, context, *, origin, cap, konteks, sesi, sumber):
    if (not isinstance(body, bytes) or len(body) > 8388608 or not isinstance(context, dict)
            or not all(type(v) is str and 0 < len(v) <= 2048 for v in (cap, konteks, sesi))
            or not isinstance(source, str) or len(source) > 4096
            or not isinstance(sumber, str) or len(sumber) != 64 or any(c not in '0123456789abcdef' for c in sumber)):
        return None
    from app.web.riwayat_detail_native import deskripsi as detail_spec
    u = urlsplit(source)
    spec = detail_spec(u.path, u.query)
    if u.scheme or u.netloc or u.fragment or not spec or not spec['variant'].startswith('riwayat-'):
        return None
    kind, identifier = spec['jenis'], spec['id']
    data = context.get('d') if kind == 'pengeringan' else context.get('k')
    if data is None:
        return None
    def field(key):
        return data.get(key) if isinstance(data, dict) else getattr(data, key, None)
    if kind == 'pengeringan' and (field('laporan_tersedia') is not True or field('lot_id') != identifier):
        return None
    if kind != 'pengeringan' and field('id') != identifier:
        return None
    meta = dict(kind=kind, id=identifier, kode=field('kode'), target=u.path + '/laporan')
    if not valid_meta(meta):
        return None
    doc = BeautifulSoup(body, 'html.parser')
    frames, mains, sessions = doc.select('.bingkai'), doc.select('#isi-halaman'), doc.select('#formulir-sesi')
    if (len(frames) != 1 or len(mains) != 1 or len(sessions) != 1
            or frames[0] not in mains[0].parents or frames[0] not in sessions[0].parents
            or frames[0].get('data-pindah-alamat') != source or frames[0].get('data-pindah-konteks') != konteks
            or doc.html is None or doc.html.get('data-versi') != cap or sessions[0].get('data-token') != sesi):
        return None
    roots = mains[0].select('[data-riwayat-' + kind + ']')
    if len(roots) != 1 or not _visible(roots[0]):
        return None
    code = roots[0].select_one('header .rhs-code')
    if code is None or code.get_text() != meta['kode']:
        return None
    links = []
    for link in roots[0].select('.rhs-actions>a[href]'):
        target = urlsplit(urljoin(origin + source, link.get('href')))
        if (target.scheme, target.netloc) != (urlsplit(origin).scheme, urlsplit(origin).netloc):
            continue
        if target.path == meta['target'] and not target.query and not target.fragment and _visible(link):
            links.append(link)
    if len(links) != 1 or len(mains[0].select('.laporan-riwayat > .laporan-isi')) != 1:
        return None
    nav = mains[0].select('.laporan-riwayat [data-laporan-kontrol]')
    if len(nav) != 1 or nav[0].get('data-aktif') != 'proses':
        return None
    return dict(versi=1, cap=cap, konteks=konteks, sesi=sesi, sumber=sumber,
                source_address=source, sumber_sha256=hashlib.sha256(source.encode()).hexdigest(), entry=meta)


def pasang(request, akun, response):
    if (request.method != 'GET' or getattr(request.state, 'akun', None) is not akun
            or getattr(request.state, 'portal_scope', None) is not None
            or getattr(akun, 'harus_ganti_sandi', None) is not False or response.status_code != 200):
        return response
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):
        return response
    context = getattr(response, 'context', None)
    if not isinstance(context, dict) or context.get('akun') is not akun:
        return response
    try:
        source = aset()['sumber']
    except (OSError, ValueError):
        return response
    from hmu_tampilan import CAP_ASET
    address = request.url.path + ('?' + request.url.query if request.url.query else '')
    data = susun_data(address, response.body, context, origin=str(request.base_url).rstrip('/'),
                      cap=CAP_ASET, konteks=context.get('PINDAH_KONTEKS'), sesi=context.get('CSRF'), sumber=source)
    marker = b'<!-- isi-halaman:akhir -->'
    if data is None or response.body.count(marker) != 1 or HOST.encode() in response.body:
        return response
    from jinja2.utils import htmlsafe_json_dumps
    attrs = ' '.join(f'{key}="{html.escape(value, quote=True)}"' for key, value in {
        'data-cap': CAP_ASET, 'data-konteks': data['konteks'], 'data-source-address': address,
        'data-source-sha': data['sumber_sha256']}.items())
    tag = f'<script type="application/json" id="{HOST}" {attrs}>'.encode() + htmlsafe_json_dumps(data).encode() + b'</script>'
    if len(tag) > 8192 or len(response.body) + len(tag) > 8388608:
        return response
    response.body = response.body.replace(marker, tag + marker, 1)
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
