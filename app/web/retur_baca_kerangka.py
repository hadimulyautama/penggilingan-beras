"""Finite staff read layouts; native return services and permissions stay owners.

A frame is not a transaction, stock balance, permission grant or record lookup.
No application/ORM import is needed to compile its public layout.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl,urlsplit

VARIANTS=('list','receipt','ticket')
TABS=(('ringkasan','Ringkasan'),('barang','Barang'),('tiket','Tiket & bobot'),('riwayat','Riwayat'))
COLUMNS={
    'applications':('Pengiriman asal','Pelanggan','Tiket timbang','Pemeriksaan'),
    'receipts':('Penerimaan / tanggal','Pelanggan','Nomor polisi','Tiket timbang','Berat diterima','Selisih'),
    'items':('Barang / merek','Mutu','Kemasan','Jumlah kemasan','Berat','Catatan','Catatan stok'),
}


def deskripsi(value):
    if type(value) is not str or not value.startswith('/') or value.startswith('//') or len(value)>4096 or any(ord(x)<32 for x in value) or '\\' in value:return None
    try:u=urlsplit(value);pairs=parse_qsl(u.query,keep_blank_values=True,max_num_fields=3,errors='strict')
    except (ValueError,UnicodeError):return None
    if u.scheme or u.netloc or u.fragment or u.path+('?' +u.query if u.query else '')!=value or len(dict(pairs))!=len(pairs):return None
    q=dict(pairs)
    positive=lambda v:type(v) is str and v.isascii() and v.isdigit() and v==str(int(v)) and 0<int(v)<=2147483647
    if u.path=='/retur':
        if set(q)-{'sebelum','sebelum_pengajuan'} or not all(positive(v) for v in q.values()):return None
        return dict(kind='list',id=None,tab=None)
    if match:=re.fullmatch(r'/retur/([1-9][0-9]{0,9})',u.path):
        if not positive(match[1]) or set(q)-{'tab_detail'} or q.get('tab_detail','ringkasan') not in dict(TABS):return None
        return dict(kind='receipt',id=int(match[1]),tab=q.get('tab_detail','ringkasan'))
    if match:=re.fullmatch(r'/retur/tiket/([1-9][0-9]{0,9})',u.path):
        if not positive(match[1]) or q:return None
        return dict(kind='ticket',id=int(match[1]),tab=None)
    return None


def akun_native(request,akun):
    if (request.method!='GET' or akun is None or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None or getattr(akun,'harus_ganti_sandi',None) is not False):return False
    from app.web.portal.scope import is_customer_read
    from app.web.layar_retur import _boleh
    return not is_customer_read(request) and _boleh(akun)


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static';meta=json.loads((folder/'kerangka-retur-baca-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=list(VARIANTS)
            or hashlib.sha256((folder/'kerangka-retur-baca-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):raise ValueError('Return read public program mismatch')
    return meta


async def susun(request,akun,*,registry):
    """Root optional metadata: actual current native predicate, zero DB reads."""
    if not akun_native(request,akun) or not isinstance(registry,dict) or not all(type(registry.get(k)) is str and 0<len(registry[k])<=2048 for k in ('cap','konteks','sesi')):return None
    return dict(versi=1,sumber=aset()['sumber'],cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],targets=['/retur'])
