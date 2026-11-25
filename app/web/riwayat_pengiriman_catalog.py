"""Final-journey targets from the actual native history DTO and visible links."""
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup
from app.web.giling_work_catalog import _visible
from app.web.riwayat_pengiriman_kerangka import FINAL, deskripsi, navigasi_native, row_metadata

HOST = 'padi-riwayat-pengiriman-catalog'


@lru_cache(maxsize=1)
def aset():
    folder = Path(__file__).parent / 'static'
    meta = json.loads((folder / 'kerangka-riwayat-pengiriman-ui.meta.json').read_text())
    if (meta.get('versi') != 1 or meta.get('variants') != ['read', 'review']
            or hashlib.sha256((folder / 'kerangka-riwayat-pengiriman-ui.js').read_bytes()).hexdigest() != meta.get('aset_sha256')):
        raise ValueError('Final journey package mismatch')
    return meta


def _address(href, source, origin):
    if not isinstance(href, str):
        return None
    u = urlsplit(urljoin(origin + source, href))
    base = urlsplit(origin)
    if (u.scheme, u.netloc) != (base.scheme, base.netloc) or u.fragment:
        return None
    return u.path + ('?' + u.query if u.query else '') if deskripsi(u.path, u.query) else None


def susun_data(source, body, context, *, origin, cap, konteks, sesi, sumber):
    if (not isinstance(body, bytes) or len(body) > 8388608 or not isinstance(context, dict)
            or not all(type(v) is str and 0 < len(v) <= 2048 for v in (cap, konteks, sesi))
            or not isinstance(source, str) or len(source) > 4096 or not isinstance(origin, str)
            or not isinstance(sumber, str) or len(sumber) != 64 or any(c not in '0123456789abcdef' for c in sumber)):
        return None
    u = urlsplit(source)
    if u.path != '/barang-keluar' or u.scheme or u.netloc or u.fragment:
        return None
    try:
        pairs = parse_qsl(u.query, keep_blank_values=True, max_num_fields=5, errors='strict')
    except (ValueError, UnicodeError):
        return None
    if len(dict(pairs)) != len(pairs) or set(dict(pairs)) - {'q', 'status', 'sejak', 'sebelum', 'pelanggan_id'}:
        return None
    cards = context.get('riwayat')
    if not isinstance(cards, list) or not cards or len(cards) > 50:
        return None
    records = []
    for card in cards:
        if not isinstance(card, dict):
            return None
        meta = row_metadata(card.get('rec'), review=context.get('BOLEH_PERINTAH'))
        if meta is None:
            return None
        records.append(meta)
    if len({r['id'] for r in records}) != len(records):
        return None
    doc = BeautifulSoup(body, 'html.parser')
    frames, mains, sessions = doc.select('.bingkai'), doc.select('#isi-halaman'), doc.select('#formulir-sesi')
    if (len(frames) != 1 or len(mains) != 1 or len(sessions) != 1
            or frames[0] not in mains[0].parents or frames[0] not in sessions[0].parents
            or frames[0].get('data-pindah-alamat') != source or frames[0].get('data-pindah-konteks') != konteks
            or doc.html is None or doc.html.get('data-versi') != cap or sessions[0].get('data-token') != sesi):
        return None
    entries = []
    for meta in records:
        matches = []
        for row in mains[0].select('section[aria-labelledby="judul-riwayat-keluar"] tr[data-detail-keluar]'):
            target = _address(row.get('data-detail-keluar'), source, origin)
            if target is None or deskripsi(*target.partition('?')[::2])['id'] != meta['id'] or not _visible(row):
                continue
            links = [a for a in row.select('td:first-child>a[href]')
                     if _address(a.get('href'), source, origin) == target and _visible(a)]
            if len(links) != 1 or links[0].get_text() != meta['kode']:
                return None
            matches.append(target)
        if len(matches) != 1:
            return None
        spec = deskripsi(*matches[0].partition('?')[::2])
        nav = navigasi_native(matches[0], meta['kode'], filter_query=spec['filter_query'], header_back=None)
        if nav is None:
            return None
        entries.append(dict(meta=meta, target=matches[0], nav=nav))
    return dict(versi=1, cap=cap, konteks=konteks, sesi=sesi, sumber=sumber,
                source_address=source, sumber_sha256=hashlib.sha256(source.encode()).hexdigest(), entries=entries)


def pasang(request, akun, response):
    if (request.method != 'GET' or request.url.path != '/barang-keluar'
            or getattr(request.state, 'akun', None) is not akun
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
    raw = htmlsafe_json_dumps(data).encode()
    if len(raw) > 262144:
        return response
    attrs = ' '.join(f'{k}="{html.escape(v, quote=True)}"' for k, v in {
        'data-cap': CAP_ASET, 'data-konteks': data['konteks'], 'data-source-address': address,
        'data-source-sha': data['sumber_sha256']}.items())
    tag = f'<script type="application/json" id="{HOST}" {attrs}>'.encode() + raw + b'</script>'
    if len(response.body) + len(tag) > 8388608:
        return response
    response.body = response.body.replace(marker, tag + marker, 1)
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
