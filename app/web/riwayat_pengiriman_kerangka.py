"""Final shipping journey READ shell; the original resource guard/reader owns data."""
from urllib.parse import parse_qsl, urlencode

FINAL = frozenset(('selesai', 'batal'))
META = frozenset(('id', 'kode', 'status', 'title', 'bersama', 'tiket', 'review'))


def deskripsi(path, query=''):
    # Reuse the existing narrow read-query validation, not a new auth policy.
    from app.web.pengiriman_detail_kerangka import deskripsi as read_spec
    spec = read_spec(path, query)
    if spec is None:
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    if any(key == 'tab_detail' for key, _ in pairs):
        return None  # The native journey has no tabs; do not invent them.
    q = dict(pairs)
    filters = {key: (q.get(key, '').strip()[:200] if key == 'q' else q.get(key, ''))
               for key in ('q', 'status', 'sejak')}
    if q.get('sebelum'):
        filters['sebelum'] = int(q['sebelum'])
    spec['filter_query'] = urlencode(filters)
    spec['kembali'] = '/barang-keluar?' + spec['filter_query'] + '#judul-riwayat-keluar'
    return spec


def row_metadata(record, *, review):
    """Loaded scalar/relationship state only: never cause lazy I/O after db exit."""
    fields = getattr(record, '__dict__', {})
    needed = ('id', 'kode', 'status', 'no_polisi', 'kiriman_id', 'timbangan_transaksi_id')
    if not all(key in fields for key in needed) or fields['status'] not in FINAL:
        return None
    plate = fields['no_polisi']
    if fields['kiriman_id'] is not None:
        if 'kiriman' not in fields:
            return None
        group = fields['kiriman']
        if group is not None:
            loaded = getattr(group, '__dict__', {})
            if 'no_polisi' not in loaded:
                return None
            plate = loaded['no_polisi']
    meta = dict(id=fields['id'], kode=fields['kode'], status=fields['status'],
                title=plate or fields['kode'], bersama=fields['kiriman_id'] is not None,
                tiket=fields['timbangan_transaksi_id'] is not None, review=review)
    return meta if valid_meta(meta) else None


def valid_meta(meta):
    return (isinstance(meta, dict) and set(meta) == META
            and type(meta['id']) is int and 0 < meta['id'] <= 2147483647
            and meta['status'] in FINAL
            and all(isinstance(meta[key], str) and 0 < len(meta[key]) <= 200 for key in ('kode', 'title'))
            and all(type(meta[key]) is bool for key in ('bersama', 'tiket', 'review')))


def navigasi_native(address, code, *, filter_query, header_back=None):
    if deskripsi(*address.partition('?')[::2]) is None or not isinstance(filter_query, str):
        return None
    from app.web.breadcrumb import aman, susun
    if header_back is not None and aman(header_back) is None:
        return None
    chain = susun(address, dict(filter_query=filter_query, breadcrumb_detail=code,
                               PENGIRIMAN_URL='/barang-keluar'), 'Riwayat pengiriman · ' + code)
    return dict(body_back='/barang-keluar?' + filter_query + '#judul-riwayat-keluar',
                header_back=header_back, chrome_back=chain['kembali'])


def memakai_dokumen(request):
    return (request.method == 'GET' and request.headers.get('X-Pindah') != '1'
            and deskripsi(request.url.path, request.url.query) is not None
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in ('document', 'empty')))


async def kerangka(request, akun, record, *, boleh_perbaiki):
    spec = deskripsi(request.url.path, request.url.query)
    if (not memakai_dokumen(request) or spec is None or akun is None
            or getattr(request.state, 'akun', None) is not akun
            or getattr(request.state, 'portal_scope', None) is not None
            or getattr(akun, 'harus_ganti_sandi', None) is not False):
        return None
    from app.web.portal.scope import is_customer_read
    from app.web.pengiriman_bertahap import boleh_baca
    if is_customer_read(request) or not await boleh_baca(akun.user):
        return None
    meta = row_metadata(record, review=boleh_perbaiki)
    if meta is None or meta['id'] != spec['id']:
        return None
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    from app.web.layar_pekerjaan import konteks_aman
    from app.web.tampilan import render
    context = await konteks_kerangka(request, akun)
    spec.update(meta=meta, stamp=penanda_konteks(request, akun) + '|' + spec['alamat'])
    response = render(request, 'riwayat_pengiriman_kerangka.html', RP=spec, **context,
                      layar='barang_keluar', kembali=konteks_aman(request.query_params.get('kembali_kerja')) or None,
                      filter_query=spec['filter_query'])
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
