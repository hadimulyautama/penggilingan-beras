"""Adaptasi identitas PadiFlow/portal ke kolektor metadata bersama."""
import hashlib,hmac,os
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from app import database
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.monitoring import PengumpulPemakaian,PelakuPemakaian,PembukaanMasuk,layar_dari
from hmu_identitas.ruang_data import RuangData

pengumpul=PengumpulPemakaian(lambda:database.SessionLocal(),'padiflow',os.getenv('RAILWAY_GIT_COMMIT_SHA',''))
ASSET=Path(__import__('hmu_identitas').__file__).parent/'assets/monitoring.js'
VERSI=hashlib.sha256(ASSET.read_bytes()).hexdigest()[:12]
router=APIRouter()


def pelaku_state(state):
    portal=state.get('portal_account')
    if portal:return PelakuPemakaian('pelanggan',portal.id)
    a=state.get('akun')
    if a:return PelakuPemakaian('staf',a.id,a.user_id,P.normal(state.get('peran_asli') or a.user.role),a.user.default_warehouse_id if state.get('gudang_kerja') else None)
    return state.get('monitoring_pelaku')


async def identitas(request):
    request.state.jangan_perpanjang_sesi=True
    from app.web import csrf
    if request.url.path.startswith('/pelanggan/'):
        from app.web.portal.security import require_customer
        await require_customer(request);a=request.state.portal_account
        actor=PelakuPemakaian('pelanggan',a.id);namespace='portal-pelanggan'
    else:
        from app.web.security import akun_opsional
        a=await akun_opsional(request)
        if not a:raise HTTPException(401,'Sesi tidak tersedia.')
        actor=pelaku_state(request.state._state);namespace=request.cookies.get('produksi_lihat','')
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None) or csrf.terbitkan_baru()
    request.state.csrf=nonce
    cap=csrf.untuk_sesi(nonce,(a.id,a.token_version),namespace)
    return actor,cap


@router.get('/monitoring/aktivitas.js')
async def skrip():return FileResponse(ASSET,media_type='application/javascript',headers={'Cache-Control':'public, max-age=3600'})


@router.get('/monitoring/konteks')
@router.get('/pelanggan/monitoring/konteks')
async def konteks(request:Request):
    if not RuangData.lingkungan():raise HTTPException(503,'Monitoring belum dikonfigurasi.')
    actor,csrf=await identitas(request)
    return JSONResponse(dict(csrf=csrf,cap=csrf),headers={'Cache-Control':'no-store'})


class Interaksi(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id:UUID
    jenis:Literal['interaksi','galat_browser']
    kode:Literal['','TypeError','ReferenceError','RangeError','Error','promise']=''
    layar:Literal['stok','pekerjaan','barang-masuk','pengiriman','pengaturan','laporan','timbang','tiket','daftar','giling','sosoh','retur','lainnya']

class Batch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cap:str=Field(max_length=128)
    kejadian:list[Interaksi]=Field(min_length=1,max_length=8)


@router.post('/monitoring/aktivitas',status_code=202)
@router.post('/pelanggan/monitoring/aktivitas',status_code=202)
async def aktivitas(request:Request,data:Batch):
    if not RuangData.lingkungan():raise HTTPException(503,'Monitoring belum dikonfigurasi.')
    actor,cap=await identitas(request)
    if not hmac.compare_digest(cap,data.cap):raise HTTPException(403,'Konteks akun berubah.')
    for e in data.kejadian:pengumpul.catat(actor,jenis=e.jenis,layar=e.layar,kode=e.kode,event_id=str(e.event_id),ua=request.headers.get('user-agent',''))
    return {'diterima':True}


async def petunjuk_masuk(request,username,gerbang,*,portal=False):
    """Penanda pembukaan tersimpan berlaku pada semua worker, tanpa mencatat username."""
    ruang=RuangData.lingkungan()
    if not ruang:return
    try:
        from app.models.portal import PortalAccount
        async with database.SessionLocal() as db:
            row=await db.scalar(select(PortalAccount if portal else Akun).where((PortalAccount.username if portal else Akun.username)==username))
            if row:
                actor=PelakuPemakaian('pelanggan',row.id) if portal else PelakuPemakaian('staf',row.id,row.user_id,P.normal(row.user.role))
                request.state.monitoring_pelaku=actor
                version=await db.scalar(select(PembukaanMasuk.generasi).where(PembukaanMasuk.company_id==ruang.company_id,PembukaanMasuk.jenis_akun==actor.jenis_akun,PembukaanMasuk.akun_id==actor.akun_id))
                gerbang.pakai_generasi(('portal:' if portal else '')+username,version or 0)
    except Exception:pass


def catat_login(request,kode):
    actor=getattr(request.state,'monitoring_pelaku',None) or PelakuPemakaian('anonim',0)
    try:pengumpul.catat(actor,jenis='login',layar='masuk',kode=kode,ua=request.headers.get('user-agent',''))
    except Exception:pass
