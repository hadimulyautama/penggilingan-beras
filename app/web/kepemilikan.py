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
from app.domain.gudang import PersediaanError
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
    from app.web.stok_navigasi import kembali_aman, alamat
    kembali = kembali_aman(request.query_params.get('kembali_stok')) or alamat('bahan' if request.query_params.get('kind') == 'pk' else 'karung' if request.query_params.get('kind') == 'karung' else 'produk')
    return await render_laci(request,'kepemilikan.html',awal=None,layar='stok',kembali=kembali,breadcrumb_detail='Riwayat alih kepemilikan')

@router.get('/kepemilikan/{ident}')
async def detail_page(ident:str,request:Request,akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        try:d=await detail(db,akun.user,ident)
        except (PermissionError,s.InventoryError,PersediaanError) as e:raise fail(e)
    return await render_laci(request,'kepemilikan.html',awal=d,layar='stok',kembali=request.query_params.get('kembali') if request.query_params.get('kembali','').startswith('/kepemilikan?') else '/kepemilikan',breadcrumb_detail=d['code'])

@router.get('/api/kepemilikan')
async def list_api(user=Depends(pengguna_aksi),kind:Literal['pk','produk','barang','curah','karung']|None=None,status:Literal['aktif','terkoreksi','dibatalkan']|None=None,q:str=Query('',max_length=100),page:int=Query(1,ge=1),legacy:bool=False):
    async with SessionLocal() as db:
        try:d=await s.listing(db,user=user,kind=kind,status=status,search=q,page=page,legacy=legacy)
        except (PermissionError,s.InventoryError,PersediaanError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.get('/api/kepemilikan/{ident}')
async def detail_api(ident:str,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:d=await detail(db,user,ident)
        except (PermissionError,s.InventoryError,PersediaanError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.get('/api/kepemilikan/{ident}/sumber')
async def sources_api(ident:int,user=Depends(pengguna_aksi),q:str=Query('',max_length=100),page:int=Query(1,ge=1)):
    async with SessionLocal() as db:
        try:d=await s.sources(db,user=user,ident=ident,search=q,page=page)
        except (PermissionError,s.InventoryError,PersediaanError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.post('/api/kepemilikan/{ident}/{phase}')
async def write(ident:int,phase:Literal['periksa','simpan'],body:Plan,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:
            d=await (s.inspect if phase=='periksa' else s.save)(db,user=user,ident=ident,req=body.model_dump())
            if phase=='simpan':await db.commit()
            else:await db.rollback()
        except (PermissionError,s.InventoryError,PersediaanError) as e:
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


class PindahPK(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sumber:str=Field(pattern=r'^(giling|tumpukan):[1-9][0-9]*$')
    warehouse_id:PositiveInt
    dari:PositiveInt|None=None
    ke:PositiveInt|None=None
    quantity:FiniteFloat=Field(gt=0)
    reason:str=Field(min_length=1,max_length=2000)
    key:str=Field(pattern=r'^[a-zA-Z0-9_-]{16,64}$')
    baseline:str=''
    review:str=''
    confirm:bool=False


@router.get('/kepemilikan/pk/baru')
async def pk_baru_page(request:Request,akun=Depends(butuh_akun)):
    from app.web.stok_navigasi import kembali_aman
    async with SessionLocal() as db:
        try:await s.izin(db,akun.user)
        except PermissionError as e:raise fail(e)
    balik=kembali_aman(request.query_params.get('kembali_stok'))
    return await render_laci(request,'pk_kepemilikan_baru.html',layar='stok',
        kembali='/kepemilikan?kind=pk'+('&kembali_stok='+__import__('urllib.parse',fromlist=['quote']).quote(balik,safe='') if balik else ''),
        breadcrumb_detail='Alihkan kepemilikan PK')


@router.get('/api/pk-kepemilikan/detail-sumber')
async def pk_detail_sumber(sumber:str='',kode:str='',pemilik_id:str='pabrik',user=Depends(pengguna_aksi)):
    from app.services import pk_kepemilikan as pk
    from app.models import MillingProcess
    async with SessionLocal() as db:
        try:
            if not sumber and kode:
                mid=await db.scalar(select(MillingProcess.id).where(MillingProcess.kode_proses==kode))
                if mid:sumber='giling:'+str(mid)
            owner=None if pemilik_id=='pabrik' else int(pemilik_id)
            src=await pk.sumber(db,user,sumber)
            if src.bebas(owner)<=0:raise s.InventoryError('Bagian sumber ini tidak tersedia; pilih sumber melalui detail stok.')
            label=await s.pihak(db,owner,'barang')
            item=dict(sumber=sumber,warehouse_id=src.stok.gudang.id,gudang=src.stok.gudang.nama,label=src.label,owner=owner,pemilik=label,tersedia=str(src.bebas(owner)))
            return JSONResponse(dict(sumber=[item],gudang=[dict(id=src.stok.gudang.id,nama=src.stok.gudang.nama)],pemilik=[]),headers={'Cache-Control':'no-store'})
        except (ValueError,s.InventoryError,PermissionError,PersediaanError) as e:raise fail(e)

@router.get('/api/pk-kepemilikan/cari-tujuan')
async def pk_cari_tujuan(q:str=Query('',max_length=100),page:int=Query(1,ge=1),dari:int|None=None,pilihan_id:int|None=Query(None,ge=1),user=Depends(pengguna_aksi)):
    from app.models import Jasa,Pelanggan
    from sqlalchemy import func,or_
    async with SessionLocal() as db:
        try:await s.izin(db,user)
        except PermissionError as e:raise fail(e)
        query=select(Jasa.id,Jasa.kode,Pelanggan.nama_pelanggan).join(Pelanggan,Jasa.pelanggan_id==Pelanggan.id).where(Jasa.status=='berjalan',Pelanggan.status=='aktif',Pelanggan.deleted_at.is_(None))
        if dari:
            origin=await db.get(Jasa,dari)
            if not origin:raise HTTPException(409,'Pemilik asal tidak tersedia.')
            query=query.where(Jasa.pelanggan_id!=origin.pelanggan_id)
        if pilihan_id is not None:query=query.where(Jasa.id==pilihan_id)
        if q.strip():query=query.where(or_(Pelanggan.nama_pelanggan.ilike('%'+q.strip()+'%'),Jasa.kode.ilike('%'+q.strip()+'%')))
        total=await db.scalar(select(func.count()).select_from(query.subquery()))
        rows=(await db.execute(query.order_by(Pelanggan.nama_pelanggan,Jasa.id).offset((page-1)*20).limit(20))).all()
        return JSONResponse(dict(items=[dict(value=r.id,label=r.nama_pelanggan+' · '+r.kode) for r in rows],total=total,page=page,pages=__import__('math').ceil(total/20)),headers={'Cache-Control':'no-store'})

@router.get('/api/pk-kepemilikan/pilihan')
async def pk_pilihan(user=Depends(pengguna_aksi)):
    from app.services import pk_kepemilikan as pk
    async with SessionLocal() as db:
        try:d=await pk.pilihan(db,user=user)
        except PermissionError as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})


@router.get('/api/pk-kepemilikan/pemilik')
async def pk_pemilik(user=Depends(pengguna_aksi)):
    from app.services import pk_kepemilikan as pk
    async with SessionLocal() as db:
        try:d=await pk.pilihan(db,user=user)
        except PermissionError as e:raise fail(e)
    return JSONResponse(d['pemilik'],headers={'Cache-Control':'no-store'})


@router.post('/api/pk-kepemilikan/{phase}')
async def pk_write(phase:Literal['periksa','simpan'],body:PindahPK,user=Depends(pengguna_aksi)):
    from app.services import pk_kepemilikan as pk
    from app.domain.gudang import PersediaanError
    async with SessionLocal() as db:
        try:
            d=await (pk.periksa_awal if phase=='periksa' else pk.simpan_awal)(db,user=user,req=body.model_dump())
            if phase=='simpan':await db.commit()
            else:await db.rollback()
        except (PermissionError,s.InventoryError,PersediaanError) as e:raise fail(e)
    return JSONResponse(d,headers={'Cache-Control':'no-store'})


@router.get('/api/pk-kepemilikan/status/{key}')
async def pk_status(key:str,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:await s.izin(db,user)
        except PermissionError as e:raise fail(e)
        e=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman=='pk-kepemilikan-awal:'+str(user.id)+':'+key,Peristiwa.jenis==s.AWAL))
        if e:
            try:await s.izin(db,user,e.muatan['warehouses'])
            except PermissionError as ex:raise fail(ex)
        return JSONResponse(dict(recorded=bool(e),id=e.id if e else None),headers={'Cache-Control':'no-store'})
