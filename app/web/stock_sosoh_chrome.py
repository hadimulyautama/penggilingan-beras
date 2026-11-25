"""Native hierarchy metadata for an already-authorized exact catalog target.

Only text/navigation metadata; no HTML, rows, stock values or authority grant.
"""
from urllib.parse import parse_qs, urlsplit


def describe(address, *, title, leaf=None, back):
    from app.web.breadcrumb import aman, susun
    if not all(type(v) is str and 0 < len(v) <= 512 for v in (title, leaf or title)) or not aman(back):
        return None
    chain = susun(address, dict(kembali=back, breadcrumb_detail=leaf or title), title)
    return dict(title=title, back=back, chain=chain)


def sosoh(address, code):
    q = parse_qs(urlsplit(address).query)
    raw = q.get('kembali_kerja', [''])[0]
    back = '/pekerjaan?tab=berjalan'
    if raw:
        # Actual native resolver, not a role/route guess in the browser.
        from app.web.layar_pekerjaan import konteks_aman
        back = konteks_aman(raw) or back
    return describe(address, title='Penyosohan '+code, leaf=code, back=back)


def stock(address, *, title, leaf=None):
    u = urlsplit(address);q = parse_qs(u.query)
    if u.path.startswith('/gudang/'):
        back = '/'
    elif u.path == '/stok/pk/detail':
        back = '/stok-pk-jasa' if q.get('jasa', ['0'])[0] == '1' else '/stok'
        filt = q.get('gudang_filter', [''])[0]
        if filt in ('g1', 'g2') or filt.startswith('wh:'):
            back += '?gudang='+filt
    else:
        back = '/stok-produk-jasa' if u.path == '/stok-produk-jasa/detail' else '/stok-produk'
    raw = q.get('kembali_stok', [''])[0]
    if raw:
        from app.web.stok_navigasi import kembali_aman
        back = kembali_aman(raw) or back
    return describe(address, title=title, leaf=leaf, back=back)
