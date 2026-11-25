"""Conservative native list-filter correlation, never server authority.

The browser uses only a private, bound, already-rendered empty native frame.
This pure descriptor does not query rows, choose a company, mint the existing
server JSON stamp or replace an alias dispatcher. Fresh same-URL GET remains
native. Unsupported input simply declines this presentation adapter.
"""
from urllib.parse import parse_qsl, urlsplit, urlencode

COMMON = ('jenis', 'kepemilikan', 'gudang', 'pemasok', 'cari',
          'pelanggan_id', 'kembali_jasa', 'halaman')
FIELDS = {
    '/barang-masuk': ('status', *COMMON),
    '/pekerjaan': ('tab', *COMMON, 'asal', 'kategori', 'grup', 'informasi'),
}
ALIASES = {
    '/berjalan': 'Native caller supplies awal=berjalan; its URL is not /pekerjaan.',
    '/aksi': 'Native dispatcher can select penerimaan or work and infer a tab from data.',
    '/keputusan': 'Native Admin dependency and asal/category filtering must run.',
    '/mutu': 'Native quality predicates and mutations/redirects are not list aliases.',
    '/aksi-lain': 'Native redirects to /pekerjaan/catat-lain; separate action catalogue.',
}


def describe(path, query=''):
    if path not in FIELDS or not isinstance(query, str) or len(query) > 3000:
        return None
    # A malformed percent/UTF-8 query is left to its native parser.
    import re
    if re.search(r'%(?![0-9A-Fa-f]{2})', query):
        return None
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=False,
                          max_num_fields=len(FIELDS[path]), errors='strict')
    except (ValueError, UnicodeError):
        return None
    q = dict(pairs)
    if len(q) != len(pairs) or set(q) - set(FIELDS[path]):
        return None
    if any(len(q.get(k, '')) > 200 for k in ('cari', 'pemasok')):
        return None
    if q.get('gudang', '') not in ('', 'g1', 'g2') or q.get('kepemilikan', '') not in ('', 'jasa', 'pabrik'):
        return None
    for key in ('jenis', 'asal', 'kategori', 'grup'):
        if q.get(key) and not re.fullmatch('[A-Za-z0-9_-]{1,80}', q[key]):
            return None
    if q.get('informasi', '') not in ('', '1'):
        return None
    for key in ('pelanggan_id', 'halaman'):
        value = q.get(key, '')
        if value and (not value.isascii() or not value.isdigit() or not 0 < int(value) <= 2147483647):
            return None
    back = q.get('kembali_jasa', '')
    if back:
        if len(back) > 1500:
            return None
        try:
            u = urlsplit(back)
        except ValueError:
            return None
        if not back.startswith('/') or back.startswith('//') or u.scheme or u.netloc or u.fragment or not re.fullmatch(r'/jasa(?:/pelanggan/[1-9][0-9]*)?', u.path):
            return None
    key, default, choices = ('status', 'belum', ('belum', 'diterima')) if path == '/barang-masuk' else ('tab', 'tindakan', ('tindakan', 'berjalan'))
    selected = q.get(key, default)
    if selected not in choices:
        return None
    address = path + ('?' + query if query else '')
    prototype = '/barang-masuk?status=' + selected if path == '/barang-masuk' else '/pekerjaan?tab=' + selected
    return dict(path=path, address=address, family='masuk' if path == '/barang-masuk' else 'pekerjaan',
                selection=selected, prototype=prototype, pairs=pairs)


def native_link(spec, **changes):
    """Equivalent to layar_pekerjaan.tautan for supported read-only pairs."""
    q = dict(spec['pairs'])
    for name in ('buka', 'nilai', 'halaman'):
        q.pop(name, None)
    q.update(changes)
    return spec['path'] + '?' + urlencode({k: v for k, v in q.items() if v})
