"""A closed set of production reads; never forward arbitrary staff routes."""
import re
from urllib.parse import urlsplit, urlencode, parse_qsl

MENU = (
    ('ringkasan','Ringkasan','ringkasan'), ('pekerjaan','Pekerjaan Saya','pekerjaan'),
    ('stok','Stok Saya','stok'), ('barang-masuk','Barang Masuk','masuk'),
    ('barang-keluar','Pengiriman & Retur','keluar'), ('riwayat-giling','Riwayat Barang','riwayat'),
    ('riwayat-qc/gabah-basah','Riwayat QC','qc'), ('laporan','Laporan','laporan'),
    ('kabar','Berita & Notifikasi','kabar'))
READS = re.compile(r'^/(?:ringkasan|pekerjaan|stok|stok-pk-jasa|stok-produk-jasa(?:/detail)?|stok-karung-jasa|stok/pk/detail|barang-masuk(?:/\d+)?|barang-keluar(?:/\d+)?|retur(?:/\d+|/tiket/\d+|/pengajuan/\d+)?|proses-aktif/(?:pengeringan|pendinginan|giling|sosoh)/[\w-]+|riwayat-(?:giling|pengeringan|sosoh|transfer)(?:/\d+(?:/laporan(?:\.pdf)?)?)?|riwayat-qc/[\w-]+(?:/[\w-]+)?|jasa/pelanggan/\d+|jasa/\d+(?:/nota(?:\.pdf)?)?|laporan|audit|kabar)$')


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
    if path.startswith('/jasa'):return 'ringkasan'
    if path.startswith('/stok'):return 'stok'
    if path.startswith('/proses-aktif'):return 'pekerjaan'
    if path.startswith('/retur'):return 'keluar'
    if path.startswith('/riwayat-qc'):return 'qc'
    if path.startswith('/riwayat-') or path=='/audit':return 'riwayat'
    return next((k for p,n,k in MENU if '/'+p==path),'ringkasan')
