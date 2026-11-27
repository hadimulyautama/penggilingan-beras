"""Adapter baca panel pesanan; bukan endpoint, izin atau penulis baru."""
import re
from urllib.parse import urlsplit, parse_qs

KEYS = {'tab', 'status', 'cari', 'halaman', 'pesanan_halaman', 'pesanan_cari', 'pesanan_status'}

def alamat(raw):
    if not isinstance(raw, str) or len(raw) > 4096 or '\\' in raw or any(ord(c) < 32 for c in raw):
        return False
    try:
        u = urlsplit(raw)
        q = parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return False
    return bool(not (u.scheme or u.netloc) and re.fullmatch(r'/jasa/pelanggan/[1-9]\d{0,9}', u.path)
                and int(u.path.rsplit('/', 1)[1]) <= 2147483647
                and u.fragment in ('', 'pesanan-pelanggan') and not (set(q)-KEYS)
                and q.get('tab', ['ringkasan']) == ['ringkasan']
                and all(len(v) == 1 and len(v[0]) <= 200 for v in q.values()))

def pasang(response, request):
    from app.web.portal.scope import is_customer_read
    if (is_customer_read(request) or getattr(request.state, 'portal_scope', None)
            or getattr(request.state, 'frame_kerangka_langsung', False)
            or not alamat(str(request.url.path)+('?' + request.url.query if request.url.query else ''))
            or b'id="pesanan-pelanggan"' not in response.body):
        return response
    from hmu_tampilan import CAP_ASET
    # Hanya aset ringan. Tidak membaca pelanggan/otoritas lagi atau menyimpan
    # HTML transaksi pada registry/cache. Server native telah mengesahkan GET.
    extra = ('<style>#pesanan-pelanggan [data-jp-hidden][hidden]{display:none!important}</style>'
             '<script src="/static/jasa-pesanan-bertahap.js?v='+CAP_ASET+'" defer></script>').encode()
    response.body = response.body.replace(b'<!-- isi-halaman:akhir -->', extra+b'<!-- isi-halaman:akhir -->', 1)
    response.headers['content-length'] = str(len(response.body))
    return response
