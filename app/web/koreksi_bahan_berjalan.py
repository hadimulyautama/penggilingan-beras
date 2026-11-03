"""Pintu koreksi berizin; rencana diperiksa ulang dalam transaksi simpan."""
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field,FiniteFloat,PositiveInt,StringConstraints
from typing import Annotated
from app.database import SessionLocal
from app.models import User,Peristiwa
from app.penggilingan.gudang1.services.milling import MillingError
from app.penggilingan.gudang2.service import Gudang2Error
from app.services import koreksi_bahan_berjalan as s
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
router=APIRouter()

class Bahan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:PositiveInt|Annotated[str,StringConstraints(pattern=r'^(broken|beras|samping):[1-9][0-9]*$')]
    sumber:str
    jumlah:FiniteFloat|None=None
    hapus:bool=False
    sisa:FiniteFloat|None=None

class Rancangan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dasar:str
    bahan:list[Bahan]=Field(default_factory=list)
    hasil:dict[str,FiniteFloat]=Field(default_factory=dict)
    alasan:str=Field(max_length=2000)
    kunci:str
    pemeriksaan:str=''
    konfirmasi:bool=False

@router.get('/koreksi-bahan/{jenis}/{kode}')
async def halaman(jenis:str,kode:str,request:Request,akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        try:d=await s.konteks(db,jenis=jenis,kode=kode,user=akun.user)
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
    return await render_laci(request,'koreksi_bahan_berjalan.html',awal=d,layar='pekerjaan',
        kembali=f'/proses-aktif/{jenis}/{kode}' if d['id'] else '/stok',breadcrumb_detail=kode)

@router.get('/api/actions/koreksi-bahan/{jenis}/{kode}')
async def baca(jenis:str,kode:str,user:User=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:d=await s.konteks(db,jenis=jenis,kode=kode,user=user)
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.post('/api/actions/koreksi-bahan/{jenis}/{kode}/{tahap}')
async def tulis(jenis:str,kode:str,tahap:str,req:Rancangan,user:User=Depends(pengguna_aksi)):
    if tahap not in ('periksa','simpan'):raise HTTPException(404,'Tahap tidak ditemukan.')
    async with SessionLocal() as db:
        try:
            body=req.model_dump(exclude_none=True)
            d=await (s.periksa if tahap=='periksa' else s.simpan)(db,jenis=jenis,kode=kode,user=user,req=body)
            if tahap=='simpan':await db.commit()
            else:await db.rollback()
        except PermissionError as e:
            await db.rollback();raise HTTPException(403,str(e))
        except IntegrityError:
            await db.rollback();raise HTTPException(409,'Hubungan sumber atau saldo berubah. Tidak ada koreksi tersimpan; pertahankan isian dan periksa kembali data terkait.')
        except (ValueError,Gudang2Error,MillingError) as e:
            await db.rollback();raise HTTPException(409,str(e))
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

@router.get('/api/actions/koreksi-bahan-status/{kunci}')
async def status(kunci:str,user:User=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        # Izin efektif tetap diperiksa bahkan setelah status proses berubah.
        try:
            try:await s.izin(db,user,'giling')
            except PermissionError:await s.izin(db,user,'sosoh')
        except PermissionError as e:raise HTTPException(403,str(e))
        row=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==f'{s.JENIS}:{user.id}:{kunci}'))
        if row:
            try:await s.izin(db,user,row.muatan['isian'][0])
            except PermissionError as e:raise HTTPException(403,str(e))
        return JSONResponse(dict(tercatat=row is not None,peristiwa_id=row.id if row else None,hasil=row.muatan.get('hasil') if row else None),headers={'Cache-Control':'no-store'})
