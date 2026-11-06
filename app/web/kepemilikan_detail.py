from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException,Request,Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from app.database import SessionLocal
from app.models import Peristiwa
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
from app.services import kepemilikan_detail as s
from app.services.kepemilikan import InventoryError
router=APIRouter()
def kembali_detail(value):
    from urllib.parse import urlsplit,parse_qsl,urlencode
    from app.web.stok_navigasi import kembali_aman
    old=kembali_aman(value)
    if old:return old
    parsed=urlsplit(value or '')
    if parsed.scheme or parsed.netloc or parsed.fragment or any(c in (value or '') for c in ('\\','\r','\n')):return '/stok'
    if parsed.path not in ('/stok/karung/detail','/stok-produk/detail','/stok-produk-jasa/detail'):return '/stok'
    allowed={'material','ukuran','merk','pemilik','sumber_page','jenis','pelanggan_id','kembali_stok'}
    args=[(k,v[:500]) for k,v in parse_qsl(parsed.query) if k in allowed]
    return parsed.path+('?' + urlencode(args) if args else '')

class Rancangan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    destination:str=Field(min_length=1,max_length=40)
    quantity:Decimal=Field(allow_inf_nan=False)
    bulk:Decimal=Field(default=0,allow_inf_nan=False)
    bulk_key:str=Field(default='',pattern=r'^(|curah:[1-9][0-9]*|curah_barang:[1-9][0-9]*)$')
    note:str=Field(default='',max_length=2000)
    baseline:str=Field(min_length=1,max_length=128)
    key:str=Field(pattern=r'^[a-zA-Z0-9_-]{16,64}$')
    review:str=''
    confirm:bool=False
def response(data):return JSONResponse(jsonable_encoder(data),headers={'Cache-Control':'no-store'})
def gagal(e):return HTTPException(403 if isinstance(e,PermissionError) else 409,str(e))

@router.get('/stok/karung/detail')
async def karung_detail(request:Request,material:str,ukuran:int,merk:str='',pemilik:str='pabrik',sumber_page:int=Query(1,ge=1),akun=Depends(butuh_akun)):
    if pemilik!='pabrik' and (not pemilik.isascii() or not pemilik.isdigit() or int(pemilik)<=0):raise HTTPException(409,'Pemilik karung tidak sah.')
    async with SessionLocal() as db:
        try:data=await s.daftar_karung(db,user=akun.user,material=material,size=ukuran,brand=merk,owner=None if pemilik=='pabrik' else int(pemilik),page=sumber_page)
        except (PermissionError,InventoryError) as e:raise gagal(e)
    return await render_laci(request,'karung_detail_sumber.html',layar='stok_karung',sumber_kepemilikan=data,identitas_karung=f'{material} · {ukuran} kg · {merk or "Tanpa merek"}',kembali='/stok?tab=karung')

@router.get('/stok/sumber/{kind}/{id:int}')
async def halaman(kind:str,id:int,request:Request,curah:str='',curah_page:int=Query(1,ge=1),akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        try:data=await s.konteks(db,user=akun.user,kind=kind,id=id,bulk_key=curah,bulk_page=curah_page)
        except (PermissionError,InventoryError) as e:raise gagal(e)
    from app.web.stok_navigasi import kembali_aman
    return await render_laci(request,'kepemilikan_sumber.html',sumber=data,layar='stok',breadcrumb_detail=data['parts'][0]['code'],kembali=kembali_detail(request.query_params.get('kembali_stok')),mulai=request.query_params.get('tindakan')=='pindah')

@router.get('/api/stok-sumber/{kind}/{id:int}')
async def konteks(kind:str,id:int,curah:str='',page:int=Query(1,ge=1),curah_page:int=Query(1,ge=1),user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:return response(await s.konteks(db,user=user,kind=kind,id=id,bulk_key=curah,page=page,bulk_page=curah_page))
        except (PermissionError,InventoryError) as e:raise gagal(e)

@router.get('/api/stok-sumber/{kind}/{id:int}/pelanggan')
async def pelanggan(kind:str,id:int,q:str=Query('',max_length=100),page:int=Query(1,ge=1),user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:return response(await s.pelanggan(db,user=user,kind=kind,id=id,q=q,page=page))
        except (PermissionError,InventoryError) as e:raise gagal(e)

@router.post('/api/stok-sumber/{kind}/{id:int}/{phase}')
async def tulis(kind:str,id:int,phase:str,body:Rancangan,user=Depends(pengguna_aksi)):
    if phase not in ('periksa','simpan'):raise HTTPException(404,'Tahap tidak dikenal.')
    async with SessionLocal() as db:
        try:
            result=await (s.periksa if phase=='periksa' else s.simpan)(db,user=user,kind=kind,id=id,req=body.model_dump())
            if phase=='simpan':await db.commit()
            else:await db.rollback()
            return response(result)
        except (PermissionError,InventoryError) as e:
            await db.rollback();raise gagal(e)
        except DBAPIError:
            await db.rollback();raise HTTPException(409,'Saldo/sumber berubah saat menyimpan. Seluruh perpindahan dibatalkan; periksa ulang dengan isian yang tetap tersimpan.')

@router.get('/api/stok-kepemilikan-status/{key}')
async def status(key:str,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:await s.s.izin(db,user)
        except PermissionError as e:raise gagal(e)
        e=await db.scalar(select(Peristiwa).where(Peristiwa.jenis==s.OP,Peristiwa.kunci_kiriman==f'kepemilikan-detail:{user.id}:{key}'))
        if e:
            kind,id=e.muatan['source'].split(':')
            try:await s.sumber(db,user,kind,int(id))
            except (PermissionError,InventoryError) as exc:raise gagal(exc)
        return response(dict(recorded=e is not None,**(e.muatan['result'] if e else {})))
