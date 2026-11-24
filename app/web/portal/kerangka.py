"""Seven native portal menu frameworks, not staff permission or business data.

The caller has already verified CustomerReader and loaded its source scope.
Only document presentation may be early; X-Portal-Navigasi reads stay native.
"""
from datetime import date
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl

ROOT=Path(__file__).resolve().parents[3]
PAGES={
 '/ringkasan':dict(title='Beranda',intro='',sections=['Barang di pabrik','Proses berjalan'],filters=[]),
 '/barang-masuk':dict(title='Barang masuk',intro='Barang Anda yang sudah diterima di pabrik.',sections=['Penerimaan tercatat'],filters=['jenis','cari']),
 '/barang-saya':dict(title='Barang saya',intro='Lihat sisa barang per jenis, lalu buka untuk melihat lokasi dan rincian batch.',sections=['Barang di pabrik','Karung kosong'],filters=[]),
 '/jasa-saya':dict(title='Proses berjalan',intro='',sections=['Proses berjalan','Menunggu giliran'],filters=[]),
 '/riwayat-proses':dict(title='Riwayat proses',intro='Proses yang sudah selesai. Buka untuk melihat bahan dan hasilnya.',sections=['Daftar riwayat proses'],filters=['jenis','q']),
 '/barang-keluar':dict(title='Pengambilan barang',intro='Barang milik Anda yang diambil atau dikirim dari pabrik.',sections=['Pengambilan berjalan','Riwayat pengambilan'],filters=['q','status','sejak']),
 '/laporan':dict(title='Dokumen',intro='Bukti barang masuk, bukti pengambilan, rekap barang, dan laporan proses.',sections=['Daftar dokumen'],filters=['jenis','q']),
}


def deskripsi(path,query=''):
    address_path=path
    if path in {'/pelanggan','/pelanggan/'}:path='/pelanggan/ringkasan'
    if not isinstance(path,str) or not path.startswith('/pelanggan/') or len(query)>2048:return None
    page=path.removeprefix('/pelanggan')
    if page not in PAGES or re.search(r'%(?![0-9A-Fa-f]{2})',query):return None
    try:pairs=parse_qsl(query,keep_blank_values=True,max_num_fields=6,errors='strict')
    except (ValueError,UnicodeError):return None
    q=dict(pairs);keys=set(PAGES[page]['filters'])|({'halaman'} if page in {'/barang-masuk','/riwayat-proses','/laporan'} else {'sebelum'} if page=='/barang-keluar' else set())
    if len(q)!=len(pairs) or set(q)-keys:return None
    for key,limit in [('cari',200),('q',120),('jenis',80),('status',40)]:
        if len(q.get(key,''))>limit:return None
    for key in ('halaman','sebelum'):
        if key in q and (not q[key].isascii() or not q[key].isdigit() or not 1<=int(q[key])<=2147483647):return None
    if q.get('sejak'):
        try:
            if date.fromisoformat(q['sejak']).isoformat()!=q['sejak']:return None
        except ValueError:return None
    return dict(page=page,alamat=address_path+('?' +query if query else ''),query=q,**PAGES[page])


@lru_cache(maxsize=1)
def aset():
    folder=ROOT/'app/web/static'
    meta=json.loads((folder/'kerangka-portal-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or set(meta.get('schemas',{}))!=set(PAGES)
        or hashlib.sha256((folder/'kerangka-portal-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Portal structure package mismatch')
    return meta


def binding(request,scope):
    from .scope import ReadScope
    if not isinstance(scope,ReadScope) or request.state.akun.user is not scope.reader:return None
    from .auth import csrf_context
    from hmu_tampilan import CAP_ASET
    from .navigation import MENU
    try:source=aset()['sumber']
    except (OSError,ValueError,KeyError,TypeError):
        import logging
        logging.getLogger(__name__).warning('Paket struktur portal belum tersedia; pembaca native dipertahankan')
        return None
    return dict(versi=1,sumber=source,cap=CAP_ASET,
        akun=str(scope.reader.account_id),sesi=csrf_context(request),
        menus=['/pelanggan/'+path for path,_,_ in MENU])


async def dokumen(original,request):
    spec=deskripsi(original.url.path,original.url.query)
    if (original.method!='GET' or spec is None or original.headers.get('X-Portal-Navigasi')=='1'
        or not (original.headers.get('Sec-Fetch-Mode')=='navigate' and original.headers.get('Sec-Fetch-Dest') in {'document','empty'})):
        return None
    scope=getattr(request.state,'portal_scope',None)
    if scope is None or binding(request,scope) is None:return None
    from .presentation import shell
    from app.web.tampilan import templates
    config=aset()['schemas'][spec['page']]
    content=templates.env.get_template('portal/kerangka.html').render(PORTAL_FRAME_SPEC=spec,PORTAL_FRAME_SCHEMA=config)
    return shell(request,content,title=spec['title'])
