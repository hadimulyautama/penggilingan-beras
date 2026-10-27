"""Empat tahap Retur ke Supplier; semua perubahan hanya pada pengajuan."""
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from hmu_identitas import peran as P
from app.database import SessionLocal
from app.models.retur_supplier import ReturSupplier
from app.services import retur_supplier as svc
from app.services import retur_supplier_detail as pembaca
from app.web.security import butuh_akun
from app.web.portal.scope import is_customer_read
from app.web.tampilan import render

router=APIRouter(tags=['webapp'])


def pekerja(request):
    if is_customer_read(request) or getattr(request.state,'portal_scope',None) is not None:
        raise HTTPException(403,'Pengajuan pembelian supplier tidak tersedia pada portal pelanggan.')


def json(data, status=200):
    from decimal import Decimal
    return JSONResponse(jsonable_encoder(data,custom_encoder={Decimal:str}),status_code=status,
                        headers={'Cache-Control':'private, no-store'})


def bersih(item):
    from decimal import Decimal
    return jsonable_encoder({k:v for k,v in item.items() if not k.startswith('_') and k not in ('tipe_pool',)},custom_encoder={Decimal:str})


def tidak_boleh(exc):
    raise HTTPException(403,str(exc)) from exc


class ItemReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kunci:StrictStr
    jumlah:StrictStr


class PeriksaReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    jumlah:list[ItemReq]
    alasan:StrictStr
    catatan:StrictStr=''


class SimpanReq(PeriksaReq):
    kunci:StrictStr
    dasar:StrictStr


class TiketReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tiket_id:StrictInt


class BatalReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    alasan:StrictStr


@router.get('/barang-masuk/{tid:int}/retur-supplier')
async def formulir(tid:int,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            t,opsi=await svc.siapkan(db,tid,akun.user)
            daftar=(await db.scalars(select(ReturSupplier).where(ReturSupplier.penerimaan_tiket_id==tid)
                                     .order_by(ReturSupplier.id.desc()))).all()
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    response=render(request,'retur_supplier.html',layar='barang_masuk',penerimaan=t,opsi=opsi,
        opsi_json=[bersih(x) for x in opsi],pengajuan=daftar,boleh_tulis=P.admin_keatas(akun.user.role),
        kunci=uuid4().hex,pemilik_draf=akun.user.id,kembali=f'/barang-masuk/{tid}')
    response.headers['Cache-Control']='private, no-store'
    return response


@router.get('/barang-masuk/{tid:int}/retur-supplier/status')
async def status_draf(tid:int,kunci:str,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            rec=await db.scalar(select(ReturSupplier).where(ReturSupplier.kunci==kunci,
                ReturSupplier.input_by==akun.user.id,ReturSupplier.penerimaan_tiket_id==tid))
            if rec:await svc.ambil(db,rec.id,akun.user)
            else:await svc.siapkan(db,tid,akun.user)
            return json(dict(ditemukan=bool(rec),alamat=f'/retur-supplier/{rec.id}' if rec else None))
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:return json(dict(detail=str(exc)),409)


@router.post('/barang-masuk/{tid:int}/retur-supplier/periksa')
async def periksa(tid:int,data:PeriksaReq,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            await svc.pelaku(db,akun.user,tulis=True)
            hasil=await svc.periksa(db,tid,akun.user,[x.model_dump() for x in data.jumlah],data.alasan,data.catatan)
            return json(dict(dasar=hasil['dasar'],items=[bersih(x) for x in hasil['items']],
                total_kg=hasil['total_kg'],total_karung=hasil['total_karung'],total_curah_kg=hasil['total_curah_kg'],
                alasan=hasil['alasan'],catatan=hasil['catatan']))
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:
        try:
            async with SessionLocal() as baru:
                _,opsi=await svc.siapkan(baru,tid,akun.user)
        except (ValueError,PermissionError):opsi=[]
        return json(dict(detail=str(exc),opsi=[bersih(x) for x in opsi]),409)


@router.post('/barang-masuk/{tid:int}/retur-supplier/simpan')
async def simpan(tid:int,data:SimpanReq,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            try:
                rec=await svc.simpan(db,user=akun.user,tid=tid,**data.model_dump())
                await db.commit()
                return json(dict(ok=True,alamat=f'/retur-supplier/{rec.id}'))
            except ValueError as exc:
                await db.rollback()
                try:
                    _,opsi=await svc.siapkan(db,tid,akun.user)
                except ValueError:
                    opsi=[]
                return json(dict(detail=str(exc),opsi=[bersih(x) for x in opsi]),409)
    except PermissionError as exc:tidak_boleh(exc)
    except DBAPIError:return json(dict(detail='Status penyimpanan belum dapat dipastikan. Periksa daftar pengajuan atau riwayat sebelum mengulang.',tidak_pasti=True),503)


@router.get('/retur-supplier/{identitas:int}')
async def detail(identitas:int,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            data=await pembaca.detail(db,identitas,akun.user)
            kandidat=await pembaca.kandidat(db,data['rec']) if data['rec'].status=='diajukan' and not data['rec'].timbangan_transaksi_id else []
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc
    from app.config import settings
    response=render(request,'retur_supplier_detail.html',layar='barang_masuk',**data,kandidat=kandidat,
        boleh_tulis=P.admin_keatas(akun.user.role),tera_url=settings.teraflow_web_url.rstrip('/'),
        kembali=f"/barang-masuk/{data['rec'].penerimaan_tiket_id}")
    response.headers['Cache-Control']='private, no-store'
    return response


@router.post('/retur-supplier/{identitas:int}/tiket')
async def tautkan(identitas:int,data:TiketReq,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            await svc.hubungkan(db,user=akun.user,identitas=identitas,tiket_id=data.tiket_id)
            await db.commit()
        return json(dict(ok=True,alamat=f'/retur-supplier/{identitas}'))
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:return json(dict(detail=str(exc)),409)
    except DBAPIError:return json(dict(detail='Status pengaitan belum dapat dipastikan. Periksa pengajuan terbaru sebelum mengulang.',tidak_pasti=True),503)


@router.post('/retur-supplier/{identitas:int}/batalkan')
async def batalkan(identitas:int,data:BatalReq,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    try:
        async with SessionLocal() as db:
            await svc.batalkan(db,user=akun.user,identitas=identitas,alasan=data.alasan)
            await db.commit()
        return json(dict(ok=True,alamat=f'/retur-supplier/{identitas}'))
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:return json(dict(detail=str(exc)),409)
    except DBAPIError:return json(dict(detail='Status pembatalan belum dapat dipastikan. Periksa status terbaru sebelum mengulang.',tidak_pasti=True),503)


class AktualReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    item_id:StrictInt
    jumlah:StrictStr
    kemasan_tara_id:StrictInt|None=None


class PemeriksaanReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    jumlah:list[AktualReq]
    alasan:StrictStr=''


class ManualReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dasar:StrictStr
    catatan:StrictStr
    konfirmasi:StrictBool


class KeluarReq(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dasar:StrictStr
    konfirmasi:StrictBool


@router.get('/retur-supplier/{identitas:int}/penyelesaian')
async def pemeriksaan_form(identitas:int,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    from app.services import retur_supplier_selesai as selesai
    from app.models import User,PackagingMaterial
    try:
        async with SessionLocal() as db:
            rec,items,aktual,tiket,opsi,hasil,kemasan=await selesai.data(db,identitas,akun.user)
            last=await selesai._terbaru(db,rec)
            pelaksana=await db.get(User,hasil.input_by) if hasil else None
            materials={x.id:x.nama for x in (await db.scalars(select(PackagingMaterial))).all()}
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    from app.config import settings
    response=render(request,'retur_supplier_selesai.html',layar='barang_masuk',rec=rec,items=items,
        aktual=aktual,tiket=tiket,opsi=opsi,hasil=hasil,terakhir=last,kemasan=kemasan,materials=materials,
        pelaksana=pelaksana.nama if pelaksana else None,boleh_tulis=(P.admin_keatas(akun.user.role) or P.operator_saja(akun.user.role)) and rec.status=='diajukan',boleh_manual=P.admin_keatas(akun.user.role),
        tiket_berubah=bool(hasil and (not tiket or selesai.versi_tiket(tiket)!=hasil.snapshot['versi_tiket'])),
        tera_url=settings.teraflow_web_url.rstrip('/'),kembali=f'/retur-supplier/{identitas}',pemilik_draf=akun.user.id)
    response.headers['Cache-Control']='private, no-store'
    return response


@router.get('/retur-supplier/{identitas:int}/penyelesaian/status')
async def penyelesaian_status(identitas:int,request:Request,akun=Depends(butuh_akun)):
    pekerja(request)
    from app.models.retur_supplier import ReturSupplierKeluar
    try:
        async with SessionLocal() as db:
            rec,_=await svc.ambil(db,identitas,akun.user)
            hasil=await db.scalar(select(ReturSupplierKeluar).where(ReturSupplierKeluar.retur_supplier_id==rec.id))
            return json(dict(status=rec.status,tercatat=bool(hasil),kode=hasil.kode if hasil else None,
                alamat=f'/retur-supplier/{rec.id}/penyelesaian'))
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:return json(dict(detail=str(exc)),404)


async def _tindakan_selesai(request,akun,identitas,aksi,**kw):
    pekerja(request)
    from app.services import retur_supplier_selesai as selesai
    try:
        async with SessionLocal() as db:
            hasil=await getattr(selesai,aksi)(db,identitas=identitas,user=akun.user,**kw)
            await db.commit()
            if aksi=='catat_keluar':return json(dict(ok=True,alamat=f'/retur-supplier/{identitas}/penyelesaian'))
            return json(hasil)
    except PermissionError as exc:tidak_boleh(exc)
    except ValueError as exc:
        terbaru=[]
        try:
            async with SessionLocal() as db:
                _,items,_,_,opsi,_,_=await selesai.data(db,identitas,akun.user)
                for i in items:
                    x=opsi.get(i.kunci_sumber)
                    if x:terbaru.append(dict(item_id=i.id,stok_kg=x['stok_kg'],maksimum=x['maksimum'],per_kg=x['per_kg'],terikat_kg=x['terikat_kg']))
        except (ValueError,PermissionError):pass
        return json(dict(detail=str(exc),opsi=terbaru),409)
    except DBAPIError:return json(dict(detail='Status tindakan belum dapat dipastikan. Isian dipertahankan; periksa status atau riwayat sebelum mengulang.',tidak_pasti=True),503)


@router.post('/retur-supplier/{identitas:int}/penyelesaian/periksa')
async def pemeriksaan_simpan(identitas:int,data:PemeriksaanReq,request:Request,akun=Depends(butuh_akun)):
    return await _tindakan_selesai(request,akun,identitas,'periksa',jumlah=[x.model_dump() for x in data.jumlah],alasan=data.alasan)


@router.post('/retur-supplier/{identitas:int}/penyelesaian/manual')
async def pemeriksaan_manual(identitas:int,data:ManualReq,request:Request,akun=Depends(butuh_akun)):
    return await _tindakan_selesai(request,akun,identitas,'manual',**data.model_dump())


@router.post('/retur-supplier/{identitas:int}/penyelesaian/keluar')
async def pemeriksaan_keluar(identitas:int,data:KeluarReq,request:Request,akun=Depends(butuh_akun)):
    return await _tindakan_selesai(request,akun,identitas,'catat_keluar',**data.model_dump())
