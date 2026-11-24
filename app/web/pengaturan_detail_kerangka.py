"""Six existing Settings read variants; native guards/values/writers stay owners."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

PATHS=tuple('/pengaturan/'+x for x in ('peran','akses','sebab-berhenti','mutu','kledo','sistem'))
VARIANTS=('peran-lihat','peran-gudang','akses','sebab-berhenti','mutu','kledo','sistem-admin','sistem-umum')


def permintaan_kerangka(request):
    return (request.method=='GET' and request.url.path in PATHS and not request.url.query
        and request.headers.get('X-Pindah')!='1'
        and (request.headers.get('X-Kerangka-Halaman')=='1'
             or request.headers.get('Sec-Fetch-Mode')=='navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


def akun_native(request,akun):
    return (request.method=='GET' and akun is not None and getattr(request.state,'akun',None) is akun
        and getattr(request.state,'portal_scope',None) is None
        and getattr(akun,'harus_ganti_sandi',None) is False)


def native_references(request,akun):
    """Actual native predicates/reference DTO, no DB/config/domain read.

    Original role is used only where native does. No four-view role inference,
    recovery policy, grant or product/tenant selector is introduced here.
    """
    if not akun_native(request,akun):return None
    from app.web.pengaturan import PERAN_ADMIN_KEATAS,_P,_proses_view,V_SUPER
    from app.web.akses import PERAN_KOLOM
    from app.web.pengaturan_navigasi import HALAMAN
    original=getattr(request.state,'peran_asli',None) or akun.peran
    can_change=_P.boleh_ganti_gudang(original)
    return dict(tuan=akun.peran in PERAN_ADMIN_KEATAS,
        peran=('lihat' if _P.admin_keatas(original) else 'gudang') if can_change else None,
        columns=[label for _,label in PERAN_KOLOM],processes=[list(row) for row in _proses_view(V_SUPER)],
        pages={p.rsplit('/',1)[-1]:HALAMAN[p.rsplit('/',1)[-1]] for p in PATHS})


def spesifikasi(path,query='',*,native):
    if path not in PATHS or query or not isinstance(native,dict) or type(native.get('tuan')) is not bool:return None
    kind=path.rsplit('/',1)[-1]
    if kind in {'sebab-berhenti','mutu','kledo'} and not native['tuan']:return None
    if native.get('peran') not in ('lihat','gudang',None):return None
    if kind=='peran' and native.get('peran') is None:return None
    if not all(isinstance(native.get(k),list) and 0<len(native[k])<=16 for k in ('columns','processes')):return None
    text=lambda x:isinstance(x,str) and 0<len(x)<=200
    if not all(text(x) for x in native['columns']) or len(set(native['columns']))!=len(native['columns']):return None
    if not all(isinstance(row,(list,tuple)) and len(row)==2 and all(text(x) for x in row) for row in native['processes']):return None
    if len({row[0] for row in native['processes']})!=len(native['processes']):return None
    if not isinstance(native.get('pages'),dict):return None
    page=native['pages'].get(kind)
    if not isinstance(page,(tuple,list)) or len(page)!=2 or not all(isinstance(x,str) and x for x in page):return None
    variant=('peran-'+native['peran']) if kind=='peran' else ('sistem-admin' if native['tuan'] else 'sistem-umum') if kind=='sistem' else kind
    heading=('Lihat sebagai' if native['peran']=='lihat' else 'Kerja di gudang') if kind=='peran' else 'Informasi versi' if kind=='sistem' and not native['tuan'] else page[1]
    return dict(alamat=path,kind=kind,variant=variant,heading=heading,group=page[0],title='Pengaturan',
        columns=native['columns'],processes=native['processes'],admin=native['tuan'])


async def kerangka(request,akun,konteks):
    if not permintaan_kerangka(request):return None
    native=native_references(request,akun)
    spec=spesifikasi(request.url.path,request.url.query,native=native)
    if spec is None:return None
    shell=konteks.get('SHELL',{})
    if shell.get('data_url')!=spec['alamat'] or not isinstance(shell.get('stamp'),str) or not shell['stamp']:return None
    from app.web.tampilan import render
    response=render(request,'pengaturan_detail_kerangka.html',
        **{**konteks,'layar':'pengaturan','PG_DETAIL_SHELL':{**spec,'stamp':shell['stamp']}})
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-pengaturan-detail-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=list(VARIANTS)
            or hashlib.sha256((folder/'kerangka-pengaturan-detail-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Settings detail public package mismatch')
    return meta


async def susun(request,akun,*,registry):
    if not isinstance(registry,dict) or not all(isinstance(registry.get(k),str) and registry[k] for k in ('cap','konteks','sesi')):return None
    native=native_references(request,akun)
    if native is None:return None
    meta=aset()
    if native['columns']!=meta.get('references',{}).get('columns') or native['processes']!=meta.get('references',{}).get('processes'):return None
    targets={path:spec['variant'] for path in PATHS if (spec:=spesifikasi(path,native=native)) is not None}
    if not targets:return None
    return dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],sumber=meta['sumber'],
        targets=targets,columns=native['columns'],processes=native['processes'])
