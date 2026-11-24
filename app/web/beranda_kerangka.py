"""Native Home structure; known greeting/scope, no warehouse or stock DTO.

Root metadata reuses its already-read light navigation context. Only a direct
native document may read that same existing navigation helper; all actual
Home collections/aggregates and action controls stay in the native reader.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

ADDRESS='/'


def permitted_document(request):
    return (request.method=='GET' and request.url.path==ADDRESS and not request.url.query
        and request.headers.get('X-Pindah')!='1'
        and (request.headers.get('X-Kerangka-Halaman')=='1'
             or request.headers.get('Sec-Fetch-Mode')=='navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


def project(*,view,meja,selepan,polesan,tamu,greeting,date):
    """Project actual native presentation inputs; this is never a role grant."""
    if (type(view) is not str or not isinstance(meja,(tuple,list,set,frozenset))
        or any(type(v) is not str for v in meja)
        or not all(type(v) is str and v for v in (selepan,polesan,tamu))
        or view not in {*meja,selepan,polesan,tamu}
        or not all(type(v) is str and 0<len(v)<=256 for v in (greeting,date))):return None
    # These are the same native labels in beranda.html, not warehouse IDs or
    # configured machine identities. No stock or entitlement is inferred.
    scope=('Semua gudang' if view in meja else 'Gudang 1 · Selepan' if view==selepan
           else 'Gudang 2 · Penyosohan' if view==polesan else 'Belum punya gudang')
    return dict(sapaan=greeting,tanggal=date,scope=scope,semua_gudang=view in meja)


def native_references(request,akun,navigasi):
    if (request.method!='GET' or akun is None or getattr(request.state,'akun',None) is not akun
        or getattr(request.state,'portal_scope',None) is not None
        or getattr(akun,'harus_ganti_sandi',None) is not False
        or not isinstance(navigasi,dict) or type(navigasi.get('MUTU_AKTIF')) is not bool):return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):return None
    from app.web.layar import MEJA,SELEPAN,POLESAN,TAMU
    from app.services.beranda import sapaan_dan_tanggal
    greeting,date=sapaan_dan_tanggal(akun.user.nama if akun.user else None)
    return project(view=getattr(request.state,'view',None),meja=MEJA,selepan=SELEPAN,
                   polesan=POLESAN,tamu=TAMU,greeting=greeting,date=date)


@lru_cache(maxsize=1)
def asset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-beranda-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=[ADDRESS]
        or hashlib.sha256((folder/'kerangka-beranda-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Native Home public structure mismatch')
    return meta


def descriptor(references,*,registry,source):
    if (not isinstance(references,dict) or set(references)!={'sapaan','tanggal','scope','semua_gudang'}
        or not all(type(references[k]) is str and 0<len(references[k])<=256 for k in ('sapaan','tanggal','scope'))
        or type(references['semua_gudang']) is not bool
        or (references['scope']!='Semua gudang' if references['semua_gudang'] else references['scope'] not in {'Gudang 1 · Selepan','Gudang 2 · Penyosohan','Belum punya gudang'})
        or not isinstance(registry,dict) or not all(type(registry.get(k)) is str and 0<len(registry[k])<=2048 for k in ('cap','konteks','sesi'))):return None
    import re
    if type(source) is not str or not re.fullmatch('[a-f0-9]{64}',source):return None
    value=dict(versi=1,sumber=source,cap=registry['cap'],konteks=registry['konteks'],
               sesi=registry['sesi'],references=references)
    from jinja2.utils import htmlsafe_json_dumps
    return value if len(htmlsafe_json_dumps(value).encode())<=4096 else None


async def susun(request,akun,*,registry,navigasi):
    """Zero new SQL: project native auth/view and Root's current nav values."""
    references=native_references(request,akun,navigasi)
    return descriptor(references,registry=registry,source=asset()['sumber']) if references else None


async def kerangka(request,akun):
    if not permitted_document(request):return None
    # Auth has already run in main.beranda. Do not read reference data for a
    # portal, unknown request-state account or mandatory-password session.
    if (akun is None or getattr(request.state,'akun',None) is not akun
        or getattr(request.state,'portal_scope',None) is not None
        or getattr(akun,'harus_ganti_sandi',None) is not False):return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):return None
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    try:navigasi=await konteks_kerangka(request,akun)
    except Exception as error:
        from fastapi import HTTPException
        if isinstance(error,HTTPException) and error.status_code in (401,403):raise
        # This optional read must not remove Home's existing partial-failure
        # handling when the reference store is unavailable.
        import logging
        logging.getLogger(__name__).warning('Struktur Beranda belum tersedia (%s)',type(error).__name__)
        return None
    references=native_references(request,akun,navigasi)
    if references is None:return None
    from app.web.tampilan import render
    response=render(request,'beranda_kerangka.html',layar='beranda',HOME_SHELL={
        'alamat':ADDRESS,'stamp':penanda_konteks(request,akun)+'|'+ADDRESS,**references},**navigasi)
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response
