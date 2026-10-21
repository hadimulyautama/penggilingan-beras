"""Konteks pelanggan adalah tautan kembali, bukan izin atau identitas transaksi."""
import re
from urllib.parse import urlsplit,parse_qsl,urlencode


def kembali_aman(nilai):
    try:
        u=urlsplit(nilai or '')
    except ValueError:
        return ''
    if u.scheme or u.netloc or not re.fullmatch(r'/jasa(?:/pelanggan/[1-9][0-9]*)?',u.path):
        return ''
    return u.path+('?' + urlencode([(k,v) for k,v in parse_qsl(u.query)
        if k in ('tab','status','cari','halaman')]) if u.query else '')
