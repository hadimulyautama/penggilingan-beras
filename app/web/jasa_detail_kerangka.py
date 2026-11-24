"""Scoped customer-detail Jasa structure proposal; no caller/registry wiring.

A customer URL is correlation, not ownership. Native auth, financial-read
predicate and local DB namespace remain authoritative; portal is not adopted.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode

TABS=(('ringkasan','Ringkasan'),('penerimaan','Penerimaan'),('proses','Proses'),
      ('stok','Stok'),('pengambilan','Pengambilan & retur'))
STATUS_PILIHAN=(('','Semua pesanan'),('berjalan','Berjalan'),('selesai','Selesai'),
                ('dibatalkan','Dibatalkan'),('digabung','Digabung'))
STATUS=tuple(key for key,_ in STATUS_PILIHAN)
_KEYS={'tab','status','cari','halaman','pesanan_halaman','pesanan_cari',
       'pesanan_status','rincian_halaman','rincian_cari'}
_PATH=re.compile(r'/jasa/pelanggan/([1-9][0-9]{0,9})')


def deskripsi(path,query=''):
    """Strict pure read slice; feedback/action/focused-order aliases stay native."""
    match=_PATH.fullmatch(path)
    if not match or int(match[1])>2147483647 or len(query)>3000 or re.search(r'%(?![0-9a-fA-F]{2})',query):
        return None
    try:pairs=parse_qsl(query,keep_blank_values=True,max_num_fields=12,errors='strict')
    except (ValueError,UnicodeError):return None
    q=dict(pairs)
    if len(q)!=len(pairs) or set(q)-_KEYS:return None
    tab=q.get('tab','ringkasan')
    if tab not in dict(TABS):return None
    for key in ('status','pesanan_status'):
        if q.get(key,'') not in STATUS:return None
    for key in ('halaman','pesanan_halaman','rincian_halaman'):
        value=q.get(key,'')
        if value and (not re.fullmatch(r'[1-9][0-9]{0,9}',value) or int(value)>2147483647):return None
    if any(len(q.get(k,''))>200 for k in ('cari','pesanan_cari','rincian_cari')):return None
    pid=int(match[1]);address=path+('?' +query if query else '')
    carry={k:v for k,v in q.items() if k.startswith('pesanan_')}
    tabs=[dict(key=k,label=label,href=path+'?'+urlencode(dict(
        tab=k,status=q.get('status',''),cari=q.get('cari',''),halaman=q.get('halaman',''),**carry)),active=k==tab) for k,label in TABS]
    return dict(pelanggan_id=pid,tab=tab,tabs=tabs,alamat=address,
        kembali='/jasa?'+urlencode({k:v for k,v in q.items() if k in ('status','cari','halaman')}),
        pesanan_cari=q.get('pesanan_cari','').strip(),pesanan_status=q.get('pesanan_status',''),status_pilihan=STATUS_PILIHAN,
        rincian_cari=q.get('rincian_cari','').strip())


async def _metadata_pelanggan(db,pid):
    """Same native existence predicate; bounded shape metadata, no ledger reads.

    Uses the same SessionLocal whose transaction is checked by pasang_pagar.
    No company selection comes from a request, header, query or customer name.
    """
    from sqlalchemy import select,text
    from app.models import Pelanggan,Jasa
    if await db.scalar(select(Pelanggan.id).where(Pelanggan.id==pid)) is None:return None
    ids=list((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id==pid).limit(21))).all())
    if not ids and not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM timbangan_transaksi WHERE arah='MASUK' AND jasa=TRUE AND pelanggan_id=:pid)"),{'pid':pid}):
        return None
    return dict(banyak_pesanan=len(ids)>20)


def kunci_cetak(body):
    """Native header retained; both native print entry points stay unavailable."""
    return body.replace(b'data-js-cetak',b'disabled aria-describedby="jasa-detail-cetak-alasan" data-js-cetak')


async def kerangka(request,akun,konteks):
    """Root calls after native butuh_akun/role guard, before heavy composer.

    Rechecking that positive guard here cannot grant a role or a customer row.
    None declines to native, including every portal and action/deep-link URL.
    """
    spec=deskripsi(request.url.path,request.url.query)
    if (request.method!='GET' or spec is None or request.headers.get('X-Pindah')=='1'
            or akun is None or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False):return None
    from app.peran import can_see_financials
    if not can_see_financials(akun.user):return None
    from app.database import SessionLocal
    async with SessionLocal() as db:
        metadata=await _metadata_pelanggan(db,spec['pelanggan_id'])
    if metadata is None:return None
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.tampilan import render
    spec.update(stamp=penanda_konteks(request,akun)+'|'+spec['alamat'],
        filter_pesanan=metadata['banyak_pesanan'] or bool(spec['pesanan_cari'] or spec['pesanan_status']))
    response=render(request,'jasa_detail_kerangka.html',JASA_DETAIL_SHELL=spec,layar='jasa',kembali=spec['kembali'],
        **{k:v for k,v in konteks.items() if k not in {'SHELL','layar','kembali','JASA_DETAIL_SHELL'}})
    # Reuse native heading/control partial, with print unavailable while read.
    response.body=kunci_cetak(response.body)
    response.headers['content-length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response
