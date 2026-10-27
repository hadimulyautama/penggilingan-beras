"""Formulir pasca-keluar; GET tidak memeriksa atau menulis mutasi."""
from uuid import uuid4
from fastapi import APIRouter,Request,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictStr,StrictInt,StrictBool,Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from hmu_identitas import peran as ROLE
from app.database import SessionLocal
from app.config import settings
from app.services import retur_supplier_koreksi as svc,retur_supplier as dasar
from app.models.retur_supplier_koreksi import ReturSupplierPerubahan as P
from app.models import Peristiwa,User
from app.web.retur_supplier import pekerja,json as jawaban
from app.web.security import butuh_akun
from app.web.tampilan import render

router=APIRouter(tags=['webapp'])


class Baris(BaseModel):
    model_config=ConfigDict(extra='forbid')
    item_id:StrictInt
    jumlah:StrictStr


class Periksa(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kunci:StrictStr
    jenis:StrictStr
    jumlah:list[Baris]=Field(default_factory=list)
    keterangan:StrictStr=''
    keberadaan:StrictStr=''
    alasan:StrictStr
    konfirmasi:StrictBool


class Simpan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kunci:StrictStr
    dasar:StrictStr
    konfirmasi:StrictBool


class Manual(Simpan):
    catatan:StrictStr


def izin(exc):raise HTTPException(403,str(exc)) from exc


@router.get('/retur-supplier/{identitas:int}/tindakan')
async def formulir(identitas:int,request:Request,jenis:str='jumlah',akun=Depends(butuh_akun)):
    pekerja(request)
    if jenis not in ('jumlah','keterangan','batal'):raise HTTPException(422,'Jenis tindakan tidak dikenal.')
    try:
        async with SessionLocal() as db:
            await dasar.pelaku(db,akun.user,tulis=True)
            data=await svc.data(db,identitas,akun.user)
    except PermissionError as exc:izin(exc)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    response=render(request,'retur_supplier_koreksi.html',**data,jenis=jenis,kunci=uuid4().hex,
        hasil=None,pemilik_draf=akun.user.id,tera_url=settings.teraflow_web_url.rstrip('/'),
        kembali=f'/riwayat-retur-supplier/{identitas}',layar='laporan_riwayat')
    response.headers['Cache-Control']='private, no-store';return response


@router.get('/retur-supplier/{identitas:int}/tindakan/hasil/{peristiwa_id:int}')
async def hasil(identitas:int,peristiwa_id:int,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            data=await svc.data(db,identitas,akun.user)
            rec=await db.get(P,peristiwa_id)
            if not rec or rec.retur_supplier_id!=identitas:raise ValueError('Tindakan bukan bagian dari retur ini.')
            pelaku=await db.get(User,rec.input_by)
    except PermissionError as exc:izin(exc)
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc
    response=render(request,'retur_supplier_koreksi.html',**data,jenis=rec.jenis,kunci='',hasil=rec,
        pelaku=pelaku.nama if pelaku else 'Tidak tercatat',pemilik_draf=akun.user.id,
        tera_url=settings.teraflow_web_url.rstrip('/'),kembali=f'/riwayat-retur-supplier/{identitas}',layar='laporan_riwayat')
    response.headers['Cache-Control']='private, no-store';return response


@router.get('/retur-supplier/{identitas:int}/tindakan/status')
async def status(identitas:int,kunci:str,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            await dasar.ambil(db,identitas,akun.user)
            rec=await db.scalar(select(P).join(Peristiwa,Peristiwa.id==P.peristiwa_id).where(P.retur_supplier_id==identitas,Peristiwa.kunci_kiriman=='retur_supplier_perubahan:'+kunci))
        return jawaban(dict(ditemukan=bool(rec),alamat=f'/retur-supplier/{identitas}/tindakan/hasil/{rec.peristiwa_id}' if rec else None))
    except PermissionError as exc:izin(exc)
    except ValueError as exc:return jawaban(dict(detail=str(exc)),404)


async def jalankan(identitas,request,akun,data,aksi):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            try:
                result=await aksi(db,user=akun.user,identitas=identitas,**data.model_dump())
                await db.commit()
                if isinstance(result,P):return jawaban(dict(ok=True,alamat=f'/retur-supplier/{identitas}/tindakan/hasil/{result.peristiwa_id}'))
                return jawaban(result)
            except ValueError as exc:
                await db.rollback()
                try:
                    fresh=await svc.data(db,identitas,akun.user)
                    terbaru=dict(versi=fresh['versi'],items=[dict(item_id=i.id,jumlah=fresh['efektif'][i.id]['jumlah'],
                        stok_kg=fresh['opsi'].get(i.kunci_sumber,{}).get('stok_kg')) for i in fresh['items']])
                except (ValueError,PermissionError):terbaru=None
                return jawaban(dict(detail=str(exc),terbaru=terbaru,periksa_ulang=True),409)
    except PermissionError as exc:izin(exc)
    except DBAPIError:return jawaban(dict(detail='Status pencatatan belum dapat dipastikan. Isian dipertahankan; periksa status atau riwayat sebelum mengulang.',tidak_pasti=True),503)


@router.post('/retur-supplier/{identitas:int}/tindakan/periksa')
async def periksa(identitas:int,data:Periksa,request:Request,akun=Depends(butuh_akun)):
    return await jalankan(identitas,request,akun,data,svc.periksa)


@router.post('/retur-supplier/{identitas:int}/tindakan/manual')
async def manual(identitas:int,data:Manual,request:Request,akun=Depends(butuh_akun)):
    return await jalankan(identitas,request,akun,data,svc.manual)


@router.post('/retur-supplier/{identitas:int}/tindakan/simpan')
async def simpan(identitas:int,data:Simpan,request:Request,akun=Depends(butuh_akun)):
    return await jalankan(identitas,request,akun,data,svc.simpan)
