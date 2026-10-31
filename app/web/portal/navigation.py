"""A closed set of production reads; never forward arbitrary staff routes."""
import re
from urllib.parse import urlsplit, urlencode, parse_qsl

MENU = (
    ('ringkasan','Beranda','ringkasan'), ('barang-masuk','Barang masuk','masuk'),
    ('barang-saya','Barang Saya','stok'), ('jasa-saya','Proses Berjalan','pekerjaan'),
    ('riwayat-proses','Riwayat proses','riwayat'),
    ('barang-keluar','Pengambilan barang','pengambilan'), ('laporan','Dokumen','laporan'))
READS = re.compile(r'^/(?:ringkasan|jasa-saya|barang-saya|riwayat-proses|pekerjaan|stok|stok-pk-jasa|stok-produk-jasa(?:/detail)?|stok-karung-jasa|stok/pk/detail|barang-masuk(?:/\d+(?:/serah-terima(?:\.pdf)?|/laporan\.pdf)?)?|barang-keluar(?:/\d+(?:/serah-terima(?:\.pdf)?)?)?|retur(?:/\d+|/tiket/\d+|/pengajuan/\d+)?|proses-aktif/(?:pengeringan|pendinginan|giling|sosoh)/[\w-]+|riwayat-(?:giling|pengeringan|sosoh|transfer)(?:/\d+(?:/laporan(?:\.pdf)?)?)?|riwayat-qc/[\w-]+(?:/[\w-]+)?|jasa/pelanggan/\d+|jasa/\d+(?:/nota(?:\.pdf)?)?|laporan|serah-terima|audit|kabar)$')


def portal_url(value):
    u=urlsplit(value)
    if u.netloc or u.scheme:return None
    path=u.path
    if path.startswith('/pelanggan/') or path=='/pelanggan':return value
    if not READS.fullmatch(path):return None
    q=dict(parse_qsl(u.query))
    if any(q.get(k) for k in ('buka','nilai','aksi','koreksi')):return None
    # Context paths remain navigation only; dispatch never takes authority from them.
    return '/pelanggan'+path+('?' +urlencode(q) if q else '')+('#'+u.fragment if u.fragment else '')


def active_menu(path):
    path=path.removeprefix('/pelanggan').rstrip('/') or '/ringkasan'
    if path=='/serah-terima' or '/serah-terima' in path:return 'laporan'
    if re.fullmatch(r'/jasa/\d+/nota(?:\.pdf)?',path):return 'laporan'
    if path.startswith('/barang-masuk'):return 'masuk'
    if path.startswith('/barang-keluar'):return 'pengambilan'
    if path=='/riwayat-proses':return 'riwayat'
    if path.startswith(('/jasa','/barang-masuk','/pekerjaan','/riwayat-')):return 'pekerjaan'
    if path.startswith(('/stok','/barang-saya','/barang-keluar','/retur')):return 'stok'
    if path.startswith('/proses-aktif'):return 'pekerjaan'
    if path=='/audit':return 'laporan'
    return next((k for p,n,k in MENU if '/'+p==path),'ringkasan')
