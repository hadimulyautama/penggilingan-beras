"""Pemilihan sumber dan permintaan transfer lokasi berbagai barang."""
from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ConfigDict, PositiveInt
from app.database import SessionLocal
from app.web.deps import pengguna_aksi
from app.services import transfer_barang as s
router=APIRouter()


class MintaTransfer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    jenis:Literal['barang','curah_barang','curah','karung','gabah','gabah_kering','pk_tumpukan','pk_giling']
    sumber_id:str=Field(min_length=1,max_length=50)
    tujuan_id:int=Field(ge=1,le=2147483647,strict=True)
    jumlah:str=Field(min_length=1,max_length=20)
    kunci:str=Field(pattern=r'^[a-f0-9]{32}$')


@router.get('/api/transfer-barang/sumber')
async def sumber(jenis:str='',gudang_id:int|None=Query(None,ge=1,le=2147483647),cari:str=Query('',max_length=200),halaman:int=Query(1,ge=1,le=10000),posisi:int=Query(0,ge=0,le=1000000),user=Depends(pengguna_aksi)):
    from app.web.pengiriman_pk import jawab,galat
    try:
        async with SessionLocal() as db:return jawab(await s.katalog(db,user=user,jenis=jenis,warehouse_id=gudang_id,cari=cari,halaman=halaman,posisi=posisi))
    except (ValueError,PermissionError) as e:raise galat(e)


@router.post('/api/transfer-barang/permintaan')
async def minta(body:MintaTransfer,user=Depends(pengguna_aksi)):
    from app.web.pengiriman_pk import jawab,galat
    try:
        async with SessionLocal() as db:return jawab(await s.minta(db,user=user,jenis=body.jenis,id=body.sumber_id,tujuan_id=body.tujuan_id,jumlah=body.jumlah,kunci_kiriman=body.kunci))
    except (ValueError,PermissionError) as e:raise galat(e)
