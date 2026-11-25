"""Pure three-viewer contracts and bounded X1 iframe presentation deferral.

Original viewer handlers retain every resource/location/status/role guard and
their scalar read. This module never reads a model, PDF or database.
"""
import re

KINDS = ('giling', 'sosoh', 'pengeringan')


def deskripsi(path, query=''):
    if not isinstance(path, str) or query:
        return None
    match = re.fullmatch(r'/riwayat-(giling|sosoh|pengeringan)/([1-9][0-9]{0,9})/laporan', path)
    if not match or int(match[2]) > 2147483647:
        return None
    return dict(kind=match[1], id=int(match[2]), alamat=path,
                detail=path.removesuffix('/laporan'), parent='/riwayat-' + match[1], pdf=path + '.pdf')


def valid_meta(meta):
    return (isinstance(meta, dict) and set(meta) == {'kind', 'id', 'kode', 'target'}
            and isinstance(meta['kode'], str) and 0 < len(meta['kode']) <= 200
            and type(meta['id']) is int and 0 < meta['id'] <= 2147483647
            and (spec := deskripsi(meta['target'])) is not None
            and spec['kind'] == meta['kind'] and spec['id'] == meta['id'])


def native_response(request, akun, response):
    """X1 only: original iframe URL deferred until the fresh HTML is installed.

Direct native document and binary endpoints are byte-for-byte untouched. The
original native share script remains intact. There is no PDF fetch here.
"""
    spec = deskripsi(request.url.path, request.url.query)
    if (spec is None or request.method != 'GET' or request.headers.get('X-Pindah') != '1'
            or request.headers.get('X-Kerangka-Halaman') != '0'
            or getattr(request.state, 'akun', None) is not akun
            or getattr(request.state, 'portal_scope', None) is not None or response.status_code != 200):
        return response
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):
        return response
    context = getattr(response, 'context', None)
    if (not isinstance(context, dict) or context.get('akun') is not akun
            or context.get('pdf_url') != spec['pdf'] or not isinstance(context.get('kode'), str)):
        return response
    from bs4 import BeautifulSoup
    from hmu_tampilan import CAP_ASET
    doc = BeautifulSoup(response.body, 'html.parser')
    frames = doc.select('#isi-halaman iframe')
    main = doc.select_one('#isi-halaman')
    if len(frames) != 1 or frames[0].get('src') != spec['pdf'] or main is None:
        return response
    needle = (' src="' + spec['pdf'] + '"').encode()
    marker = b'<!-- isi-halaman:akhir -->'
    if response.body.count(needle) != 1 or response.body.count(marker) != 1:
        return response
    replacement = (' data-ppv-src="' + spec['pdf'] + '" data-ppv-url="' + spec['alamat'] + '"').encode()
    body = response.body.replace(needle, replacement, 1)
    asset = ('<script src="/static/proses-pdf-native.js?v=' + CAP_ASET + '" defer></script>').encode()
    response.body = body.replace(marker, asset + marker, 1)
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
