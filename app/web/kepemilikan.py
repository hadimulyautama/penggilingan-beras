"""Riwayat, detail, dan rancangan koreksi kepemilikan; izin efektif di server."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request,Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field,FiniteFloat,PositiveInt
from sqlalchemy import select
from app.models import Peristiwa
from app.database import SessionLocal
from app.services import kepemilikan as s
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
router=APIRouter()
class Plan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['ubah','batal']
    quantity:FiniteFloat|None=None
    customer:PositiveInt|None=None
    source_ids:list[PositiveInt]=Field(default_factory=list,max_length=100)
    reason:str=Field(max_length=2000)
    baseline:str
    key:str=Field(pattern=r'^[a-zA-Z0-9_-]{16,64}$')
    review:str=''
    confirm:bool=False

def fail(e):return HTTPException(403 if isinstance(e,PermissionError) else 409,str(e))
async def detail(db,user,ident):
    if ident.startswith('lama-') and ident[5:].isdigit():return await s.legacy_detail(db,user=user,ident=int(ident[5:]))
    if not ident.isdigit():raise s.InventoryError('Identitas transaksi tidak sah.')
    return await s.context(db,user=user,ident=int(ident))

@router.get('/kepemilikan')
async def list_page(request:Request,akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        try:await s.izin(db,akun.user)
        except PermissionError as e:raise fail(e)
    return await render_laci(request,'kepemilikan.html',awal=None,layar='stok',kembali='/stok',breadcrumb_detail='Pindah kepemilikan')

@router.get('/kepemilikan/{ident}')
async def detail_page(ident:str,request:Request,akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        try:d=await detail(db,akun.user,ident)
        except (PermissionError,s.InventoryError) as e:raise fail(e)
    return await render_laci(request,'kepemilikan.html',awal=d,layar='stok',kembali=request.query_params.get('kembali') if request.query_params.get('kembali','').startswith('/kepemilikan?') else '/kepemilikan',breadcrumb_detail=d['code'])

@router.get('/api/kepemilikan')
async def list_api(user=Depends(pengguna_aksi),kind:Literal['produk','barang','curah','karung']|None=None,status:Literal['aktif','terkoreksi','dibatalkan']|None=None,q:str=Query('',max_length=100),page:int=Query(1,ge=1),legacy:bool=False):
    async with SessionLocal() as db:
        try:d=await s.listing(db,user=user,kind=kind,status=status,search=q,page=page,legacy=legacy)
        except (PermissionError,s.InventoryError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.get('/api/kepemilikan/{ident}')
async def detail_api(ident:str,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:d=await detail(db,user,ident)
        except (PermissionError,s.InventoryError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.get('/api/kepemilikan/{ident}/sumber')
async def sources_api(ident:int,user=Depends(pengguna_aksi),q:str=Query('',max_length=100),page:int=Query(1,ge=1)):
    async with SessionLocal() as db:
        try:d=await s.sources(db,user=user,ident=ident,search=q,page=page)
        except (PermissionError,s.InventoryError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.post('/api/kepemilikan/{ident}/{phase}')
async def write(ident:int,phase:Literal['periksa','simpan'],body:Plan,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:
            d=await (s.inspect if phase=='periksa' else s.save)(db,user=user,ident=ident,req=body.model_dump())
            if phase=='simpan':await db.commit()
            else:await db.rollback()
        except (PermissionError,s.InventoryError) as e:
            await db.rollback();raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.get('/api/kepemilikan-status/{key}')
async def status_api(key:str,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:await s.izin(db,user)
        except PermissionError as e:raise fail(e)
        e=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman=='kepemilikan-koreksi:'+str(user.id)+':'+key,Peristiwa.jenis==s.UBAH))
        if e:
            try:await s.izin(db,user,e.muatan['after']['warehouses'])
            except PermissionError as ex:raise fail(ex)
        return JSONResponse(dict(recorded=bool(e),event_id=e.id if e else None,root_id=e.muatan['root_id'] if e else None),headers={'Cache-Control':'no-store'})
