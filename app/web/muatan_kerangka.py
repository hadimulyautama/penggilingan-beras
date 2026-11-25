"""Canonical Muatan structure only; native guard/data/controller remain owners."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ADDRESS='/muatan'


def permitted_document(request):
    return (request.method=='GET' and request.url.path==ADDRESS and not request.url.query
        and request.headers.get('X-Pindah')!='1'
        and (request.headers.get('X-Kerangka-Halaman')=='1'
             or request.headers.get('Sec-Fetch-Mode')=='navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


def current_account(request,akun):
    if (request.method!='GET' or akun is None or getattr(request.state,'akun',None) is not akun
        or getattr(request.state,'portal_scope',None) is not None
        or getattr(akun,'harus_ganti_sandi',None) is not False
        or getattr(akun,'user',None) is None):return False
    from app.web.portal.scope import is_customer_read
    return not is_customer_read(request)


def project(*,can_record,can_read_financial):
    """Only exact native predicate outcomes; never infer permission from VIEW."""
    if type(can_record) is not bool or type(can_read_financial) is not bool:return None
    return {'can_record':can_record} if can_record or can_read_financial else None


async def native_permission(request,akun):
    if not current_account(request,akun):return None
    from app.web.muatan import boleh_catat
    from app.peran import can_see_financials
    return project(can_record=await boleh_catat(akun.user),can_read_financial=can_see_financials(akun.user))


@lru_cache(maxsize=1)
def asset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-muatan-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=[ADDRESS]
        or hashlib.sha256((folder/'kerangka-muatan-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Native Muatan public structure mismatch')
    return meta


def descriptor(permission,*,registry,source):
    if (not isinstance(permission,dict) or set(permission)!={'can_record'}
        or type(permission['can_record']) is not bool
        or not isinstance(registry,dict) or not all(type(registry.get(k)) is str and 0<len(registry[k])<=2048 for k in ('cap','konteks','sesi'))
        or type(source) is not str or not re.fullmatch('[a-f0-9]{64}',source)):return None
    value=dict(versi=1,sumber=source,cap=registry['cap'],konteks=registry['konteks'],
               sesi=registry['sesi'],permission=permission)
    from jinja2.utils import htmlsafe_json_dumps
    return value if len(htmlsafe_json_dumps(value).encode())<=4096 else None


async def susun(request,akun,*,registry):
    # One actual native guard evaluation per private document, not per row.
    # Operator G1/G2 checks may read warehouse references. No board/stock read.
    permission=await native_permission(request,akun)
    return descriptor(permission,registry=registry,source=asset()['sumber']) if permission is not None else None


async def kerangka(request,akun,*,boleh):
    # This helper is called only AFTER the native route's exact wajib guard.
    if not permitted_document(request) or not current_account(request,akun) or type(boleh) is not bool:return None
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    try:navigasi=await konteks_kerangka(request,akun)
    except Exception as error:
        from fastapi import HTTPException
        if isinstance(error,HTTPException) and error.status_code in (401,403):raise
        import logging
        logging.getLogger(__name__).warning('Struktur Muatan belum tersedia (%s)',type(error).__name__)
        return None
    from app.web.tampilan import render
    response=render(request,'muatan_kerangka.html',layar='catat_muatan',MUAT_SHELL={
        'alamat':ADDRESS,'stamp':penanda_konteks(request,akun)+'|'+ADDRESS,'can_record':boleh},**navigasi)
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response
