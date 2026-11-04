from uuid import uuid4
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,StrictStr,StrictBool
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from app.database import SessionLocal
from app.models import Peristiwa
from app.web.security import butuh_akun
from app.web.koreksi_pengiriman import pekerja
from app.web.tampilan import render_laci
from app.services import koreksi_pengemasan_asal as s
from app.services.koreksi_pengiriman import cap
from app.penggilingan.gudang2.service import Gudang2Error
router=APIRouter()
class Isian(BaseModel):
    model_config=ConfigDict(extra='forbid')
    catatan_id:StrictInt
    aksi:StrictStr
    kg:StrictStr=''
    alasan:StrictStr
    kunci:StrictStr
class Simpan(Isian):
    dasar:StrictStr
    konfirmasi:StrictBool
@router.get('/pengemasan-otomatis/sosoh/{pid:int}/{kind}')
async def halaman(pid:int,kind:str,request:Request,sebelum:int|None=None,riwayat_sebelum:int|None=None,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:d=await s.data(db,pid,kind,akun.user,sebelum=sebelum,riwayat_sebelum=riwayat_sebelum)
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except ValueError as e:raise HTTPException(409,str(e)) from e
    response=await render_laci(request,'pengemasan_otomatis.html',**d,actor_id=akun.user.id,kunci=uuid4().hex,layar='stok')
    response.headers['Cache-Control']='private, no-store';return response
async def jalankan(pid,kind,akun,req,save):
    try:
        async with SessionLocal() as db:
            payload=req.model_dump(exclude={'dasar','konfirmasi','kunci'})
            if save:
                if not req.konfirmasi:raise ValueError('Konfirmasi dampak wajib diisi.')
                event=await s.simpan(db,pid,kind,akun.user,payload,dasar=req.dasar,kunci=req.kunci)
                await db.commit();return dict(ok=True,id=event.id,tujuan=f'/pengemasan-otomatis/sosoh/{pid}/{kind}#hasil-{req.catatan_id}')
            plan=await s.rencana(db,pid,kind,akun.user,payload)
            return dict(rencana=plan,dasar=cap(plan))
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except (ValueError,Gudang2Error) as e:raise HTTPException(409,str(e)) from e
    except DBAPIError as e:raise HTTPException(503,'Hasil penyimpanan belum pasti. Periksa status operasi sebelum mengulang; isian tetap tersedia.') from e
@router.post('/api/actions/pengemasan-otomatis/{pid:int}/{kind}/periksa')
async def periksa(pid:int,kind:str,req:Isian,request:Request,akun=Depends(butuh_akun)):
    pekerja(request);return await jalankan(pid,kind,akun,req,False)
@router.post('/api/actions/pengemasan-otomatis/{pid:int}/{kind}/simpan')
async def simpan(pid:int,kind:str,req:Simpan,request:Request,akun=Depends(butuh_akun)):
    pekerja(request);return await jalankan(pid,kind,akun,req,True)
@router.get('/api/actions/pengemasan-otomatis/{pid:int}/{kind}/status')
async def status(pid:int,kind:str,kunci:str,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            from app.services.koreksi_bahan_berjalan import izin
            from app.services.barang_keluar import _kunci_saldo_keluar
            await izin(db,akun.user,'sosoh')
            await _kunci_saldo_keluar(db)
            event=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==f'{s.JENIS}:{akun.user.id}:{kunci}'))
            if event and (event.muatan['proses_id']!=pid or event.muatan['jenis']!=kind):raise HTTPException(404,'Operasi tidak ditemukan.')
            return dict(ditemukan=bool(event),tujuan=f'/pengemasan-otomatis/sosoh/{pid}/{kind}')
    except PermissionError as e:raise HTTPException(403,str(e)) from e
    except ValueError as e:raise HTTPException(409,str(e)) from e
