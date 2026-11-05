"""Pengaturan fasilitas; memakai otorisasi efektif dan CSRF aplikasi."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import Warehouse, Dryer, JenisProsesProduksi, LiniProduksi
from app.services.fasilitas import simpan_jenis, simpan_lini, FasilitasError, PENJALAN
from app.web.security import butuh_super
from app.web.tampilan import render
from app.web.nav import lencana

router=APIRouter()

async def halaman(request, akun, *, err='', form=None):
    async with SessionLocal() as db:
        jenis=list((await db.execute(select(JenisProsesProduksi).order_by(JenisProsesProduksi.id))).scalars())
        lini=list((await db.execute(select(LiniProduksi).order_by(LiniProduksi.warehouse_id,LiniProduksi.id))).scalars())
        gudang=list((await db.execute(select(Warehouse).order_by(Warehouse.id))).scalars())
        dryer=list((await db.execute(select(Dryer).order_by(Dryer.id))).scalars())
    return render(request,'fasilitas.html',layar='pengaturan',kembali='/pengaturan',jenis=jenis,lini=lini,
        gudang=gudang,dryer=dryer,penjalan=PENJALAN,err=err,isian=form or {},**await lencana(akun.user))

@router.get('/pengaturan/fasilitas')
async def daftar(request:Request, akun=Depends(butuh_super)):
    return await halaman(request,akun)

@router.post('/pengaturan/fasilitas')
async def simpan(request:Request, akun=Depends(butuh_super)):
    form=dict(await request.form())
    try:
        def angka(k):return int(form[k]) if form.get(k) else None
        data=dict(user=akun.user,nama=form.get('nama',''),kode=form.get('kode',''),
                  aktif=form.get('aktif')=='on',id=angka('id'),versi=angka('versi'))
        async with SessionLocal() as db:
            if form.get('objek')=='jenis':await simpan_jenis(db,**data)
            elif form.get('objek')=='lini':
                await simpan_lini(db,**data,warehouse_id=angka('warehouse_id'),
                    jenis_proses_id=angka('jenis_proses_id'),dryer_id=angka('dryer_id'))
            else:raise FasilitasError('Tindakan tidak dikenal.')
            await db.commit()
    except (FasilitasError,ValueError) as exc:
        return await halaman(request,akun,err=str(exc),form=form)
    except IntegrityError:
        return await halaman(request,akun,err='Data telah berubah atau kode sudah digunakan. Periksa kembali.',form=form)
    from app.web.tampilan import redirect
    return redirect('/pengaturan/fasilitas?tersimpan=1')
