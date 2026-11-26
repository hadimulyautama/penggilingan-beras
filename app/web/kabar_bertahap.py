"""Kerangka Kabar tanpa isi/hitungan; pembaca dan POST tetap native."""
from functools import lru_cache
from inspect import signature
from pathlib import Path
import re
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError


@lru_cache(maxsize=1)
def validator():
    from app.web.layar_kabar import halaman_kabar
    params=signature(halaman_kabar).parameters
    return {k: (TypeAdapter(Annotated[p.annotation,p.default]),p.default.default)
            for k in ('batas','sampai','sebelum') for p in [params[k]]}


def parameter(request):
    result={k:request.query_params.get(k,'') for k in ('tab','jenis')}
    for key,(adapter,default) in validator().items():
        try:
            result[key]=adapter.validate_python(request.query_params.get(key,default))
        except ValidationError as error:
            raise RequestValidationError([{**e,'loc':('query',key,*e['loc'])}
                                          for e in error.errors()]) from error
    return result


def query_kerangka(request):
    q=request.query_params
    return (len(request.url.query)<=2000
        and all(k in {'tab','jenis','batas','sampai','sebelum'} and len(q.getlist(k))==1 for k in q)
        and q.get('tab','') in ('','belum') and len(q.get('jenis',''))<=200
        and all(not q.get(k) or re.fullmatch(r'\d{1,18}',q[k]) for k in ('batas','sampai','sebelum')))


def memakai(request):
    from app.web.halaman_bertahap import memakai_kerangka
    return (query_kerangka(request)
            and not getattr(request.state,'menyusun_kerangka_langsung',False)
            and memakai_kerangka(request,'kabar'))


@lru_cache(maxsize=1)
def aset():
    root=Path(__file__).resolve().parents[2];result=[];total=0
    for name,folder,tag in (('kabar-feed.css','hmu_tampilan','style'),
                            ('kabar-kontrol.js','hmu_tampilan','script'),
                            ('kabar-kerangka.js','app/web','script'),
                            ('halaman-bertahap.js','app/web','script')):
        code=(root/folder/'static'/name).read_text()
        if name=='kabar-feed.css':
            # Alias root selama data belum siap: badge native hanya menangani
            # .kb yang sudah lengkap, sehingga tidak mengaktifkan aksi dini.
            code=re.sub(r'(?<![\w-])\.kb(?![\w-])',':is(.kb,.kb-kerangka)',code)
        if name=='kabar-kontrol.js':
            old="document.querySelector('.kb')"
            if code.count(old)!=1:raise ValueError('Kontrol Kabar berubah')
            code=code.replace(old,"document.querySelector('.kb-kerangka')")
        total+=len(code.encode())
        if not code or total>196608 or '</'+tag in code.lower():raise ValueError('Batas aset Kabar tidak sesuai')
        if tag=='style' and re.search(r'@import|url\s*\(',code,re.I):raise ValueError('Aset Kabar membutuhkan URL tambahan')
        result.append(dict(name=name,tag=tag,code=code))
    return tuple(result)


async def kerangka(request,akun,*,navigasi=None):
    from app.web.halaman_bertahap import konteks_kerangka,penanda
    from app.web.tampilan import render
    values=parameter(request)
    values['tab']='belum' if values['tab']=='belum' else ''
    def href(**q):
        return '/kabar?'+urlencode({k:v for k,v in (values|q).items() if v is not None})
    context=dict(await konteks_kerangka(request,akun) if navigasi is None else navigasi)
    context.update(layar='kabar',KABAR=None,tab=values['tab'],href_kabar=href,
        KABAR_ASET=aset(),SHELL=dict(kind='kabar',stamp=penanda(request,akun,'kabar'),
            data_url='/api/halaman-bertahap/kabar'+('?' +request.url.query if request.url.query else '')))
    response=render(request,'kabar_bertahap.html',**context)
    response.headers['Cache-Control']='private, no-store'
    return response


async def susun(request,akun,*,navigasi):
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.kerangka_langsung import kemas_frame
    from app.web.security import NAMA_COOKIE,baca_token
    from app.web import csrf
    from hmu_tampilan import CAP_ASET
    state={**request.scope.get('state',{}),'menyusun_kerangka_langsung':True,'frame_kerangka_langsung':True}
    native=Request({**request.scope,'path':'/kabar','raw_path':b'/kabar','query_string':b'','state':state})
    response=await kerangka(native,akun,navigasi=navigasi)
    if response.status_code!=200 or len(response.body)>524288:return None
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None)
    return dict(versi=1,cap=CAP_ASET,konteks=penanda_konteks(request,akun),
        sesi=csrf.untuk_sesi(nonce,baca_token(request.cookies.get(NAMA_COOKIE)),request.cookies.get('produksi_lihat','')),
        **kemas_frame({'/kabar':response.body.decode()}))
