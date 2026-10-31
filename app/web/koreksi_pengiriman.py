"""Pascaverifikasi: formulir → dampak → konfirmasi; tidak memakai undo."""
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr
from sqlalchemy.exc import DBAPIError
from app.database import SessionLocal
from app.models import KoreksiPengiriman
from app.services import koreksi_pengiriman as svc, barang_keluar as bk
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router=APIRouter()


def pekerja(request):
    if getattr(request.state,'portal_scope',None) is not None:
        raise HTTPException(403,'Portal pelanggan hanya membaca pengiriman yang diizinkan.')


class Barang(BaseModel):
    model_config=ConfigDict(extra='forbid')
    item_id: StrictInt
    pilih: StrictStr=''
    jumlah: StrictStr


class Periksa(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kunci: StrictStr
    pelanggan_id: StrictInt
    barang: list[Barang]
    alasan: StrictStr
    sebab_selisih: StrictStr=''
    konfirmasi: StrictBool


class Simpan(Periksa):
    dasar: StrictStr


@router.get('/barang-keluar/{rid:int}/koreksi-selesai')
async def formulir(rid:int,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:data=await svc.data(db,rid,akun.user)
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (ValueError,bk.BarangKeluarError) as e:raise HTTPException(409,str(e)) from e
    response=await render_laci(request,'koreksi_pengiriman.html',**data,kunci=uuid4().hex,actor_id=akun.user.id)
    response.headers['Cache-Control']='private, no-store'
    return response


@router.get('/api/actions/koreksi-pengiriman/{rid:int}/status')
async def status(rid:int,kunci:str,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            svc.izin(akun.user)
            await bk._kunci_saldo_keluar(db)
            await svc.ambil(db,rid,akun.user)
            row=await db.get(KoreksiPengiriman,kunci)
            if row and (row.outgoing_record_id!=rid or row.input_by!=akun.user.id):
                raise HTTPException(404,'Koreksi tidak ditemukan untuk permintaan ini.')
            return dict(ditemukan=bool(row),versi=row.versi if row else None)
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (ValueError,bk.BarangKeluarError) as e:raise HTTPException(409,str(e)) from e


async def jalankan(rid,akun,req,simpan):
    try:
        async with SessionLocal() as db:
            payload=req.model_dump(exclude={'kunci','dasar'})
            if simpan:
                row=await svc.simpan(db,rid,akun.user,payload,dasar=req.dasar,kunci=req.kunci)
                await db.commit()
                return dict(ok=True,versi=row.versi,tujuan=f'/barang-keluar/{rid}/koreksi-selesai')
            _,_,plan=await svc.rencana(db,rid,akun.user,payload)
            # Pemeriksaan hanya membaca; tidak menyimpan status/stock/draf.
            return dict(rencana=plan,dasar=svc.cap(plan))
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (ValueError,bk.BarangKeluarError) as e:raise HTTPException(409,str(e)) from e
    except DBAPIError as e:
        raise HTTPException(503,'Status penyimpanan belum dapat dipastikan. Pertahankan isian dan periksa status/riwayat sebelum mengulang.') from e


@router.post('/api/actions/koreksi-pengiriman/{rid:int}/periksa')
async def periksa(rid:int,req:Periksa,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    return await jalankan(rid,akun,req,False)


@router.post('/api/actions/koreksi-pengiriman/{rid:int}/simpan')
async def simpan(rid:int,req:Simpan,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    return await jalankan(rid,akun,req,True)
