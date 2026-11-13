"""Pintu transfer PK generik dan kontrak historis Pos Timbang."""
from types import SimpleNamespace
from fastapi import APIRouter, Depends, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,PositiveInt,ConfigDict
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User,Warehouse,Silo,PermintaanPk,MillingProcess,PengirimanPk
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
from app.services import pengiriman_pk as s
from app.services.transfer import TransferError
from app.penggilingan.gudang2.service import Gudang2Error
from app.peran import can_see_financials
from hmu_identitas import peran as P
router=APIRouter()

class Item(BaseModel):
    permintaan_id:PositiveInt
    berat_kg:str=Field(max_length=20)
class Persetujuan(Item):
    tujuan:str=Field(max_length=120)
class Setujui(BaseModel):
    items:list[Persetujuan]=Field(min_length=1,max_length=50)
class Buat(BaseModel):
    model_config=ConfigDict(extra='forbid')
    items:list[Item]=Field(min_length=1,max_length=50)
    kunci:str=Field(pattern=r'^[a-f0-9]{32}$')
class Alasan(BaseModel):alasan:str=Field(min_length=1,max_length=2000)

async def baca_izin(db,u):
    if u.status!='aktif':raise PermissionError('Akun tidak aktif.')
    w=await db.get(Warehouse,u.default_warehouse_id) if u.default_warehouse_id else None
    if not can_see_financials(u) and not (P.operator_saja(u.role) and w and w.kode_fungsi in ('g1','g2')):raise PermissionError('Halaman transfer mengikuti akses gudang asal dan tujuan.')
    return w

def galat(e):return HTTPException(403 if isinstance(e,PermissionError) else 409,str(e))
def jawab(d):return JSONResponse(d,headers={'Cache-Control':'private, no-store'})

@router.get('/transfer-bertahap')
async def halaman(request:Request,akun=Depends(butuh_akun)):
    try:
        async with SessionLocal() as db:await baca_izin(db,akun.user)
    except PermissionError as e:raise galat(e)
    from app.config import settings
    return await render_laci(request,'pengiriman_pk.html',layar='pekerjaan',teraflow_url=settings.teraflow_web_url.rstrip('/'))

@router.get('/api/transfer-bertahap')
async def daftar(user=Depends(pengguna_aksi)):
    try:
        async with SessionLocal() as db:
            w=await baca_izin(db,user);is_admin=can_see_financials(user)
            from app.services.cakupan_fasilitas import lokasi_banyak
            from app.services.transfer import pending_transfer_kg
            from app.services.jasa import nama_pemilik_banyak
            rows=(await db.execute(select(PermintaanPk,MillingProcess).join(MillingProcess,MillingProcess.id==PermintaanPk.milling_process_id).where(PermintaanPk.status.in_(['diminta','disetujui'])|PermintaanPk.bertahap.is_(True)).order_by(PermintaanPk.waktu_minta,PermintaanPk.id))).all()
            loc=await lokasi_banyak(db,MillingProcess,[p.id for r,p in rows]);owners=await nama_pemilik_banyak(db,{r.jasa_id for r,p in rows if r.jasa_id})
            people={u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({r.diminta_oleh for r,p in rows})))).all()}
            requests=[]
            for r,p in rows:
                asal=loc[p.id]['warehouse_id']
                if not is_admin:
                    if w.kode_fungsi=='g1' and w.id!=asal:continue
                    if w.kode_fungsi=='g2' and r.jasa_id is not None:continue
                allocated=await s.terpakai(db,r.id);completed=await s.terpakai(db,r.id,selesai=True)
                requests.append(dict(peminta=people.get(r.diminta_oleh,'Pencatat belum tercatat'),selesai_kg=s.angka(completed),perjalanan_kg=s.angka(allocated-completed),id=r.id,lot=p.kode_proses,pemilik=owners.get(r.jasa_id,'Milik pabrik'),status=r.status,sebab=r.sebab,waktu=r.waktu_minta.isoformat() if r.waktu_minta else None,bertahap=r.bertahap,asal_id=asal,asal=loc[p.id]['gudang_nama'],diminta=s.angka(r.berat_minta_kg),disetujui=s.angka(r.berat_setuju_kg),sisa=s.angka(max(s.D(0),s.D(r.berat_setuju_kg)-allocated)),bebas=s.angka(await pending_transfer_kg(db,p.id,pemilik_id=r.jasa_id,bebas=True)),tujuan=r.tujuan,silo_id=r.silo_id))
            journeys=[]
            q=select(PengirimanPk).order_by(PengirimanPk.id.desc()).limit(100)
            if not is_admin:q=q.where(PengirimanPk.asal_id==w.id if w.kode_fungsi=='g1' else (PengirimanPk.tujuan_id==w.id)&PengirimanPk.jasa_id.is_(None))
            for j in (await db.scalars(q)).all():journeys.append(await s.rincian(db,j.id))
            from app.penggilingan.gudang2.service import _g2_warehouse_id
            from app.penggilingan.silo_policy import boleh_masuk
            target=await db.get(Warehouse,await _g2_warehouse_id(db))
            silos=[x for x in (await db.scalars(select(Silo).where(Silo.warehouse_id==target.id,Silo.aktif.is_(True)).order_by(Silo.nama_silo))).all() if boleh_masuk(x,'pk','g2')]
            tujuan=[dict(nilai='ditumpuk',nama='Tumpukan · '+target.nama_gudang)]+[dict(nilai=x.nama_silo,nama=x.nama_silo+' · '+target.nama_gudang,id=x.id) for x in silos]
            return jawab(dict(admin=is_admin,boleh_kirim=is_admin or w.kode_fungsi=='g1',permintaan=requests,pengiriman=journeys,tujuan=tujuan,gudang_tujuan=dict(id=target.id,nama=target.nama_gudang)))
    except (s.PengirimanError,TransferError,Gudang2Error,PermissionError) as e:raise galat(e)

@router.post('/api/transfer-bertahap/setujui')
async def setujui(body:Setujui,user=Depends(pengguna_aksi)):
    try:
        async with SessionLocal() as db:return jawab(await s.setujui_banyak(db,user=user,items=[x.model_dump() for x in body.items]))
    except (s.PengirimanError,TransferError,Gudang2Error,PermissionError) as e:raise galat(e)

@router.post('/api/transfer-bertahap/pengiriman')
async def buat(body:Buat,user=Depends(pengguna_aksi)):
    try:
        async with SessionLocal() as db:return jawab(await s.buat(db,user=user,items=[x.model_dump() for x in body.items],kunci=body.kunci,pakai_kendaraan=False))
    except (s.PengirimanError,TransferError,Gudang2Error,PermissionError) as e:raise galat(e)

@router.post('/api/transfer-bertahap/permintaan/{rid}/tutup-sisa')
async def tutup_sisa(rid:int,body:Alasan,user=Depends(pengguna_aksi)):
    try:
        async with SessionLocal() as db:return jawab(await s.tutup_sisa(db,rid=rid,user=user,alasan=body.alasan))
    except (s.PengirimanError,PermissionError) as e:raise galat(e)

@router.post('/api/transfer-bertahap/permintaan/{rid}/tolak')
async def tolak(rid:int,body:Alasan,user=Depends(pengguna_aksi)):
    from app.services.permintaan_pk import tolak as menolak,PermintaanError
    try:
        s.admin(user)
        async with SessionLocal() as db:
            await s.kunci_stok(db)
            r=await db.scalar(select(PermintaanPk).where(PermintaanPk.id==rid).with_for_update())
            if not r or r.status!='diminta':raise s.PengirimanError('Permintaan sudah berubah; baca ulang daftar.')
            await menolak(db,user=user,permintaan_id=rid,sebab=body.alasan)
            return jawab(dict(ok=True))
    except (s.PengirimanError,PermintaanError,PermissionError) as e:raise galat(e)

@router.post('/api/transfer-bertahap/{pid}/terima-selisih')
async def selisih(pid:int,body:Alasan,user=Depends(pengguna_aksi)):
    try:
        s.admin(user)
        async with SessionLocal() as db:
            j=await db.get(PengirimanPk,pid)
            if not j or j.tiket_id is None:raise s.PengirimanError('Pengiriman belum memiliki hasil timbang.')
            return jawab(await s.sinkron(db,pid=pid,tid=j.tiket_id,user=user,alasan=body.alasan))
    except (s.PengirimanError,TransferError,Gudang2Error,PermissionError) as e:raise galat(e)

@router.post('/api/transfer-bertahap/{pid}/batal')
async def batal(pid:int,body:Alasan,user=Depends(pengguna_aksi)):
    try:
        async with SessionLocal() as db:return jawab(await s.batalkan(db,pid=pid,user=user,alasan=body.alasan))
    except (s.PengirimanError,TransferError,Gudang2Error,PermissionError) as e:raise galat(e)

async def akun_internal(db,token,ident,lihat):
    from app.web.internal import _pastikan_token
    from hmu_identitas.model import Akun
    from hmu_identitas import pintu
    _pastikan_token(token)
    a=await db.get(Akun,ident) if ident else None;u=await db.get(User,a.user_id) if a else None
    if not a or a.status!='aktif' or not u or u.status!='aktif' or not pintu.boleh_masuk(u.role,pintu.PRODUKSI):raise HTTPException(403,'Akun tidak memiliki akses PadiFlow.')
    role=P.peran_efektif(u.role,lihat);wid=u.default_warehouse_id
    _,wh=P.urai(lihat)
    if P.operator_saja(role) and wh and P.boleh_ganti_gudang(u.role):wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh,Warehouse.aktif.is_(True)))
    return SimpleNamespace(id=u.id,role=role,status=u.status,default_warehouse_id=wid)

@router.get('/internal/pk/pengiriman/{pid}')
async def plan(pid:int,x_internal_token:str|None=Header(default=None),x_operator_akun:int|None=Header(default=None),x_produksi_lihat:str|None=Header(default=None)):
    try:
        async with SessionLocal() as db:
            u=await akun_internal(db,x_internal_token,x_operator_akun,x_produksi_lihat)
            data=await s.rincian(db,pid);w=await baca_izin(db,u)
            if not data['pakai_kendaraan']:raise s.PengirimanError('Transfer tanpa kendaraan tidak menggunakan tiket kendaraan.')
            if not can_see_financials(u) and w.id not in (data['lintasan']['asal']['gudang_id'],data['lintasan']['tujuan']['gudang_id']):raise PermissionError('Perjalanan berada di luar gudang tugas Anda.')
            return jawab(data)
    except (s.PengirimanError,TransferError,Gudang2Error,PermissionError) as e:raise galat(e)

@router.post('/internal/pk/pengiriman/{pid}/sinkron/{tid}')
async def sinkron(pid:int,tid:int,x_internal_token:str|None=Header(default=None)):
    from app.web.internal import _pastikan_token
    _pastikan_token(x_internal_token)
    try:
        async with SessionLocal() as db:return jawab(await s.sinkron(db,pid=pid,tid=tid))
    except (s.PengirimanError,TransferError,Gudang2Error) as e:raise galat(e)
