"""Halaman riwayat hanya GET; tidak memiliki tindakan mutasi."""
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import DBAPIError
from hmu_identitas import peran as P
from app.database import SessionLocal
from app.config import settings
from app.services import riwayat_retur_supplier as svc
from app.web.retur_supplier import pekerja
from app.web.security import butuh_akun
from app.web.tampilan import render
from app.web.laporan_navigasi import siapkan

router=APIRouter(tags=['webapp'])
PATH='/riwayat-retur-supplier'
PARAM=('q','awal','akhir','status','supplier','gudang','penerimaan','halaman')
TABS=(('ringkasan','Ringkasan'),('timbang','Timbang & verifikasi'),('stok','Stok'),('jejak','Jejak & dokumen'))


def konteks(request,**ganti):
    data={k:request.query_params[k] for k in PARAM if request.query_params.get(k)}
    for k,v in ganti.items():
        if v in ('',None):data.pop(k,None)
        else:data[k]=v
    return urlencode(data)


async def tampil(request,nama,**data):
    await siapkan(request,data)
    response=render(request,nama,**data)
    response.headers['Cache-Control']='private, no-store'
    return response


@router.get(PATH)
async def daftar(request:Request,q:str='',awal:str='',akhir:str='',status:str='',supplier:str='',
        gudang:str='',penerimaan:str='',halaman:int=1,akun=Depends(butuh_akun)):
    pekerja(request)
    error=None;status_code=200
    try:
        def identitas(v):
            if not v:return None
            if not v.isascii() or not v.isdigit() or int(v)<1:raise ValueError('Pilihan filter tidak sah.')
            return int(v)
        supplier,gudang,penerimaan=map(identitas,(supplier,gudang,penerimaan))
        if len(q)>200:raise ValueError('Pencarian maksimal 200 karakter.')
        async with SessionLocal() as db:
            data=await svc.daftar(db,akun.user,q=q,awal=awal,akhir=akhir,status=status,supplier=supplier,
                gudang=gudang,penerimaan=penerimaan,halaman=halaman)
    except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
    except ValueError as exc:
        # Isian filter tetap terlihat; jangan diam-diam menampilkan hasil lain.
        error=str(exc);data=None
    except DBAPIError:
        error='Riwayat belum dapat dimuat. Filter tetap tersedia; coba baca ulang. Tidak ada perubahan transaksi.';data=None;status_code=503
    return await tampil(request,'riwayat_retur_supplier.html',data=data,error=error,
        statuses=svc.STATUS,filter=dict(q=q,awal=awal,akhir=akhir,status=status,supplier=supplier,gudang=gudang,penerimaan=penerimaan),
        konteks=konteks(request),href=lambda **x:PATH+'?'+konteks(request,**x),status_code=status_code)


@router.get(PATH+'/{identitas:int}')
async def detail(identitas:int,request:Request,tab:str='ringkasan',akun=Depends(butuh_akun)):
    pekerja(request)
    if tab not in dict(TABS):raise HTTPException(404,'Bagian riwayat tidak ditemukan.')
    try:
        async with SessionLocal() as db:
            efektif,_=await svc.cakupan(db,akun.user)
            data=await svc.detail(db,identitas,akun.user)
    except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc
    except DBAPIError:
        return await tampil(request,'riwayat_retur_supplier_gagal.html',kembali=PATH+'?'+konteks(request),status_code=503)
    return await tampil(request,'riwayat_retur_supplier_detail.html',**data,tab=tab,tabs=TABS,
        statuses=svc.STATUS,kembali=PATH+'?'+konteks(request),
        boleh_koreksi_selesai=bool(data['ledger'] and data['rec'].status=='selesai_gudang' and P.admin_keatas(efektif.role) and not(data['state'] and data['state'].dibatalkan)),
        tab_href=lambda t:PATH+f'/{identitas}?'+konteks(request)+'&tab='+t,
        tera_url=settings.teraflow_web_url.rstrip('/'),
        boleh_lanjut=data['rec'].status=='diajukan' and not data['ledger'] and
            (P.admin_keatas(efektif.role) or bool(data['rec'].timbangan_transaksi_id) and P.operator_saja(efektif.role)))
