"""Active shipping READ structure only; native row and permission stay authoritative."""
from __future__ import annotations
import re
from urllib.parse import parse_qsl, urlencode

TABS=(('ringkasan','Ringkasan'),('barang','Barang'),('tiket','Tiket & bobot'),('riwayat','Retur & riwayat'))
KEYS=frozenset(('tab_detail','q','status','sejak','sebelum','pelanggan_id','kembali','kembali_kerja'))
ACTIVE=frozenset(('perintah','dimuat'))


def deskripsi(path,query=''):
    match=re.fullmatch(r'/barang-keluar/([1-9][0-9]{0,9})',path)
    if not match or int(match[1])>2147483647 or len(query)>3000 or re.search(r'%(?![0-9a-fA-F]{2})',query):return None
    try:pairs=parse_qsl(query,keep_blank_values=True,max_num_fields=12,errors='strict')
    except (ValueError,UnicodeError):return None
    q=dict(pairs)
    if len(q)!=len(pairs) or set(q)-KEYS or q.get('tab_detail','ringkasan') not in dict(TABS):return None
    # Unknown native filter values are not normalized into a different request.
    if q.get('status','') not in ('','perintah','dimuat','selesai','batal') or len(q.get('q',''))>200:return None
    for key in ('sebelum','pelanggan_id'):
        if q.get(key) and (not re.fullmatch(r'[1-9][0-9]{0,9}',q[key]) or int(q[key])>2147483647):return None
    if q.get('sejak'):
        from datetime import date
        try:
            if date.fromisoformat(q['sejak']).isoformat()!=q['sejak']:return None
        except ValueError:return None
    for key in ('kembali','kembali_kerja'):
        if q.get(key):
            value=q[key]
            if (not value.startswith('/') or value.startswith('//') or '\\' in value or '#' in value
                    or any(c in value for c in ('\r','\n'))
                    or value.partition('?')[0] not in ('/pekerjaan','/barang-keluar','/retur','/stok','/riwayat','/laporan','/jasa')):return None
    target=path+('?' +query if query else '')
    carry=[(k,v) for k,v in pairs if k!='tab_detail']
    filter_query=urlencode({k:(q.get(k,'').strip()[:200] if k=='q' else q.get(k,'')) for k in ('q','status','sejak')})
    asal=q.get('kembali_kerja',q.get('kembali',''))
    body_back=asal if asal.partition('?')[0] in ('/pekerjaan','/barang-keluar','/retur','/stok','/riwayat','/laporan','/jasa') else '/barang-keluar?'+filter_query
    return dict(id=int(match[1]),alamat=target,tab=q.get('tab_detail','ringkasan'),filter_query=filter_query,
        tabs=[dict(key=k,label=n,href=path+'?'+urlencode([*carry,('tab_detail',k)]),active=k==q.get('tab_detail','ringkasan')) for k,n in TABS],
        kembali=body_back)


def navigasi_native(address,code,*,filter_query,header_back=None):
    """Bind actual native display context through the native breadcrumb policy."""
    spec=deskripsi(*address.partition('?')[::2])
    if spec is None or not isinstance(filter_query,str):return None
    from app.web.breadcrumb import aman,susun
    if header_back is not None and (not header_back or aman(header_back) is None):return None
    chain=susun(address,dict(kembali=header_back,filter_query=filter_query,breadcrumb_detail=code,
                            PENGIRIMAN_URL='/barang-keluar'),code)
    return dict(body_back=spec['kembali'],header_back=header_back,chrome_back=chain['kembali'])


def row_metadata(record,items,*,boleh_perintah,boleh_muat):
    """Only a native-selected record/items enters; no lookup, balance or new rule."""
    if record.status not in ACTIVE:return None
    from app.services import barang_keluar as svc
    from app.web.layar_keluar import KEADAAN,_tombol
    fast=not record.kiriman_id and svc.boleh_keluar_cepat(items)
    state=KEADAAN[record.status][0]
    if record.status=='perintah' and fast:state='Menunggu penyerahan · <200 kg'
    return dict(id=record.id,kode=record.kode,status=record.status,keadaan=state,
        jasa=record.jasa_id is not None or any(i.jasa_id is not None for i in items),cepat=fast,
        bersama=bool(record.kiriman_id),tiket=bool(record.timbangan_transaksi_id),
        boleh_perintah=boleh_perintah,boleh_muat=boleh_muat,
        actions=[dict(label=label,bagian='barang' if key=='tambah_barang_keluar' else 'ringkasan')
                 for key,_,label,_ in _tombol(record,boleh_perintah=boleh_perintah,boleh_muat=boleh_muat,cepat=fast)])


def valid_meta(meta):
    if (not isinstance(meta,dict) or set(meta)!={'id','kode','status','keadaan','jasa','cepat','bersama','tiket','boleh_perintah','boleh_muat','actions'}
            or type(meta['id']) is not int or not 0<meta['id']<=2147483647
            or meta['status'] not in ACTIVE
            or not all(type(meta[k]) is bool for k in ('jasa','cepat','bersama','tiket','boleh_perintah','boleh_muat'))
            or not all(isinstance(meta[k],str) and 0<len(meta[k])<=200 for k in ('kode','keadaan'))
            or not isinstance(meta['actions'],list) or len(meta['actions'])>10):return False
    return all(isinstance(a,dict) and set(a)=={'label','bagian'} and a['bagian'] in ('ringkasan','barang')
               and isinstance(a['label'],str) and 0<len(a['label'])<=200 for a in meta['actions'])


def memakai_dokumen(request):
    return (request.method=='GET' and request.headers.get('X-Pindah')!='1'
            and deskripsi(request.url.path,request.url.query) is not None
            and (request.headers.get('X-Kerangka-Halaman')=='1'
                 or request.headers.get('Sec-Fetch-Mode')=='navigate'
                 and request.headers.get('Sec-Fetch-Dest') in ('document','empty')))


async def kerangka(request,akun,record,items,*,boleh_perintah,boleh_muat):
    spec=deskripsi(request.url.path,request.url.query)
    if (not memakai_dokumen(request) or spec is None
            or akun is None or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None or getattr(akun,'harus_ganti_sandi',None) is not False
            or record.id!=spec['id'] or record.status not in ACTIVE):return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):return None
    from app.web.pengiriman_bertahap import boleh_baca
    if not await boleh_baca(akun.user):return None
    meta=row_metadata(record,items,boleh_perintah=boleh_perintah,boleh_muat=boleh_muat)
    if not valid_meta(meta):return None
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    from app.web.layar_pekerjaan import konteks_aman
    from app.web.tampilan import render
    context=await konteks_kerangka(request,akun)
    spec.update(meta=meta,stamp=penanda_konteks(request,akun)+'|'+spec['alamat'])
    # Exactly render_laci's native mobile-header context. Content-back and
    # breadcrumb-back have different native contracts and must stay distinct.
    header_back=konteks_aman(request.query_params.get('kembali_kerja')) or None
    response=render(request,'pengiriman_detail_kerangka.html',PD=spec,**context,layar='barang_keluar',
                    kembali=header_back,filter_query=spec['filter_query'])
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response
