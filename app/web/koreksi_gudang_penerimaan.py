"""Pemeriksaan dan penyimpanan koreksi lokasi dari detail Barang Masuk."""
from fastapi import APIRouter,Depends,HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field,PositiveInt
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from app.database import SessionLocal
from app.models import Peristiwa
from app.web.deps import pengguna_aksi
from app.services import koreksi_gudang_penerimaan as s
router=APIRouter()

class Rancangan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    warehouse_id:PositiveInt
    alasan:str=Field(min_length=1,max_length=2000)
    dasar:str=Field(min_length=1,max_length=64)
    kunci:str=Field(min_length=16,max_length=64,pattern=r'^[a-zA-Z0-9_-]+$')
    pemeriksaan:str=''
    konfirmasi:bool=False

def response(value):return JSONResponse(jsonable_encoder(value),headers={'Cache-Control':'no-store'})

@router.get('/api/actions/koreksi-gudang-penerimaan/status/{key}')
async def status(key:str,user=Depends(pengguna_aksi)):
    try:s.izin(user)
    except PermissionError as e:raise HTTPException(403,str(e))
    async with SessionLocal() as db:
        row=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==f'{s.JENIS}:{user.id}:{key}',Peristiwa.jenis==s.JENIS))
        return response(dict(tercatat=row is not None,peristiwa_id=row.id if row else None,hasil=row.muatan['hasil'] if row else None))

@router.get('/api/actions/koreksi-gudang-penerimaan/{tid:int}/{kind}/{id:int}')
async def baca(tid:int,kind:str,id:int,user=Depends(pengguna_aksi)):
    async with SessionLocal() as db:
        try:return response(await s.konteks(db,user=user,tid=tid,kind=kind,id=id))
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:raise HTTPException(409,str(e))

@router.post('/api/actions/koreksi-gudang-penerimaan/{tid:int}/{kind}/{id:int}/{step}')
async def tulis(tid:int,kind:str,id:int,step:str,req:Rancangan,user=Depends(pengguna_aksi)):
    if step not in ('periksa','simpan'):raise HTTPException(404,'Tahap tidak dikenal.')
    async with SessionLocal() as db:
        try:
            result=await (s.periksa if step=='periksa' else s.simpan)(db,user=user,tid=tid,kind=kind,id=id,req=req.model_dump())
            if step=='simpan':await db.commit()
            else:await db.rollback()
            return response(result)
        except PermissionError as e:
            await db.rollback();raise HTTPException(403,str(e))
        except ValueError as e:
            await db.rollback();raise HTTPException(409,str(e))
        except DBAPIError:
            await db.rollback();raise HTTPException(409,'Saldo atau relasi berubah saat menyimpan. Seluruh koreksi dibatalkan; isian tetap tersedia. Baca data terbaru dan periksa kembali.')
