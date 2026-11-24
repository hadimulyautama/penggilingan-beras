"""Bentuk baca pengguna saja; seluruh guard dan penulis tetap native."""
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl,urlsplit

ROOT=Path(__file__).resolve().parents[2]
VARIANTS=('staf','staf-super','staf-detail','pelanggan','pelanggan-detail')
SOURCES=('/pengaturan','/pengguna','/pengguna/pelanggan')


def spesifikasi(path,query=''):
    if type(path) is not str or type(query) is not str or len(query)>2048 or re.search(r'%(?![0-9a-fA-F]{2})',query):return None
    staff=re.fullmatch(r'/pengguna(?:/([1-9][0-9]{0,9}))?',path)
    customer=re.fullmatch(r'/pengguna/pelanggan(?:/([1-9][0-9]{0,9}))?',path)
    if staff:
        if query:return None
        ident=staff[1];kind='staf-detail' if ident else 'staf'
        search=''
    elif customer:
        ident=customer[1];kind='pelanggan-detail' if ident else 'pelanggan'
        try:pairs=parse_qsl(query,keep_blank_values=True,max_num_fields=2,errors='strict')
        except (ValueError,UnicodeError):return None
        params=dict(pairs)
        if len(params)!=len(pairs) or set(params)-{'cari_akun','halaman_akun'}:return None
        # Native normalises/clamps the page after its count. Before data the
        # pagination is unknown; never claim the raw number is valid/current.
        if 'halaman_akun' in params and not re.fullmatch(r'[0-9]{1,9}',params['halaman_akun']):return None
        search=params.get('cari_akun','').strip()[:100]
    else:return None
    if ident and int(ident)>2147483647:return None
    address=path+('?' +query if query else '')
    return dict(kind=kind,id=int(ident) if ident else None,alamat=address,search=search,
        kembali='/pengguna' if kind=='staf-detail' else '/pengaturan')


def permintaan(request):
    return request.method=='GET' and request.headers.get('X-Pindah')!='1' and (
        request.headers.get('X-Kerangka-Halaman')=='1' or request.headers.get('Sec-Fetch-Mode')=='navigate'
        and request.headers.get('Sec-Fetch-Dest') in {'document','empty'})


def akun_native(request,akun):
    return akun is not None and getattr(request.state,'akun',None) is akun and getattr(request.state,'portal_scope',None) is None and getattr(akun,'harus_ganti_sandi',None) is False


def catat_guard(request,actor,jenis):
    """Caller hanya setelah Depends native positif; memo per-request/object."""
    if jenis not in {'staf','pelanggan'} or not akun_native(request,actor):return
    setattr(request.state,'pengguna_guard_'+jenis,actor)


async def pintu_native(request,akun):
    if not akun_native(request,akun):return None
    from app.web.security import butuh_super,AksesDitolak
    from app.web.portal.admin import super_only
    from fastapi import HTTPException
    allowed={}
    for kind,guard in [('staf',butuh_super),('pelanggan',super_only)]:
        if getattr(request.state,'pengguna_guard_'+kind,None) is akun:
            allowed[kind]=True;continue
        try:await guard(akun)
        except AksesDitolak:allowed[kind]=False
        except HTTPException as error:
            if error.status_code!=403:raise
            allowed[kind]=False
        else:allowed[kind]=True;catat_guard(request,akun,kind)
    return allowed


@lru_cache(maxsize=1)
def metadata():
    path=ROOT/'app/web/pengguna_baca_schema.py'
    spec=importlib.util.spec_from_file_location('native_users_schema',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.load(ROOT)


async def kerangka(request,akun,*,jenis,staff_row=None,customer_id=None):
    if not permintaan(request) or not akun_native(request,akun):return None
    spec=spesifikasi(request.url.path,request.url.query)
    if spec is None or jenis not in {'staf','pelanggan'} or not spec['kind'].startswith(jenis):return None
    # Caller dependency already admitted the actual actor. This object-bound
    # note avoids repeating its legacy recovery read on the same request.
    if getattr(request.state,'pengguna_guard_'+jenis,None) is not akun:return None
    flags=await pintu_native(request,akun)
    if not flags or not flags[jenis]:return None
    name=''
    if spec['kind']=='staf-detail':
        if staff_row is None or staff_row.id!=spec['id']:return None
        name=staff_row.nama
        if type(name) is not str or not name.strip() or len(name)>200:return None
    elif spec['kind']=='pelanggan-detail':
        if customer_id!=spec['id']:return None
        # The same native join gates resource existence. Data GET declines
        # before this branch, so page() still performs its original read once.
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.models import Pelanggan
        from app.models.portal import PortalAccount
        from fastapi import HTTPException
        async with SessionLocal() as db:
            found=await db.scalar(select(PortalAccount.id).join(Pelanggan,Pelanggan.id==PortalAccount.pelanggan_id).where(PortalAccount.id==customer_id).limit(1))
        if found is None:raise HTTPException(404,'Akun pelanggan tidak ditemukan.')
    variant='staf-super' if spec['kind']=='staf' and flags['pelanggan'] else spec['kind']
    shape=metadata();title=name if variant=='staf-detail' else shape['titles'][variant]
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    from app.web.tampilan import render
    context=await konteks_kerangka(request,akun)
    spec.update(variant=variant,title=title,nama=name,customer=flags['pelanggan'],roles=shape['roles'],columns=shape['columns'],stamp=penanda_konteks(request,akun)+'|'+spec['alamat'])
    response=render(request,'pengguna_baca_native.html',**{**context,'PENGGUNA_BACA':spec,'layar':'pengaturan' if jenis=='pelanggan' else 'pengguna_ubah' if variant=='staf-detail' else 'pengguna_kelola','kembali':spec['kembali']})
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response


@lru_cache(maxsize=1)
def aset():
    folder=ROOT/'app/web/static';meta=json.loads((folder/'kerangka-pengguna-ui.meta.json').read_text())
    if meta.get('versi')!=1 or meta.get('variants')!=list(VARIANTS) or hashlib.sha256((folder/'kerangka-pengguna-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256'):raise ValueError('Paket pengguna tidak cocok')
    return meta


async def susun(request,akun,*,registry):
    if request.method!='GET' or not akun_native(request,akun):return None
    if request.url.path!='/pengaturan' and spesifikasi(request.url.path,request.url.query) is None:return None
    if not isinstance(registry,dict) or not all(type(registry.get(k)) is str and 0<len(registry[k])<=2048 for k in ('cap','konteks','sesi')):return None
    flags=await pintu_native(request,akun)
    targets={}
    if flags['staf']:targets['/pengguna']='staf-super' if flags['pelanggan'] else 'staf'
    if flags['pelanggan']:targets['/pengguna/pelanggan']='pelanggan'
    if not targets:return None
    return dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],sumber=aset()['sumber'],targets=targets)


def katalog(html,*,source_address,permission):
    """Only actual authorised native list hrefs; never synthesize IDs/users."""
    from app.web.giling_work_catalog import _visible
    from bs4 import BeautifulSoup
    if type(html) is not str or len(html.encode())>8*1024*1024 or type(source_address) is not str or len(source_address)>4096 or not isinstance(permission,dict):return None
    try:source=urlsplit(source_address)
    except ValueError:return None
    if source.scheme or source.netloc or source.fragment or source.path not in {'/pengguna','/pengguna/pelanggan'}:return None
    spec=spesifikasi(source.path,source.query)
    if spec is None or source.path not in permission.get('targets',{}):return None
    for key in ('cap','konteks','sesi','sumber'):
        if type(permission.get(key)) is not str or not permission[key] or len(permission[key])>2048:return None
    if set(permission)!={'versi','cap','konteks','sesi','sumber','targets'} or permission.get('versi')!=1 or permission['sumber']!=aset()['sumber']:return None
    targets=permission['targets']
    if not isinstance(targets,dict) or not targets or len(targets)>2 or any(not ((path=='/pengguna' and variant in {'staf','staf-super'}) or (path=='/pengguna/pelanggan' and variant=='pelanggan')) for path,variant in targets.items()):return None
    if '/pengguna/pelanggan' in targets and targets.get('/pengguna')!='staf-super':return None
    doc=BeautifulSoup(html,'html.parser');entries=[];seen=set()
    staff=source.path=='/pengguna'
    rows=doc.select('.daftar-standar > .daftar-standar__baris') if staff else doc.select('.kelola-portal table tbody tr')
    for row in rows:
        if not _visible(row):continue
        for link in row.select('a[href]'):
            href=link.get('href','')
            if not _visible(link) or link.has_attr('target') or link.has_attr('download') or link.get('aria-disabled')=='true':continue
            target=spesifikasi(href)
            if target is None or target['kind']!=('staf-detail' if staff else 'pelanggan-detail') or href in seen:continue
            if staff:
                label=row.select_one('.baris__nama')
                if label is None:continue
                title=label.get_text(' ',strip=True)
                if not title or len(title)>200:continue
            else:title=metadata()['titles']['pelanggan-detail']
            seen.add(href);entries.append(dict(alamat=href,variant=target['kind'],title=title))
    maximum=200 if staff else 20
    if len(entries)>maximum:return None
    result=dict(versi=1,sumber=permission['sumber'],source_address=source_address,
        source_sha256=hashlib.sha256(source_address.encode()).hexdigest(),cap=permission['cap'],
        konteks=permission['konteks'],sesi=permission['sesi'],entries=entries)
    encoded=json.dumps(result,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return result if len(encoded.encode())<=131072 else None
