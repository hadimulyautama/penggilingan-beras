"""Data perusahaan hanya tersedia untuk Super Admin, tanpa pintu darurat."""
from fastapi import APIRouter, Depends, Request, HTTPException
from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render, redirect
from app.services.perusahaan import simpan, BATAS_LOGO
from hmu_dokumen.perusahaan import baca

router=APIRouter(tags=['webapp'])

async def butuh_perusahaan(akun=Depends(butuh_akun)):
    # Pemulihan akun pertama tetap milik pengelolaan pengguna. Identitas
    # penerbit dokumen tidak ikut dibuka ketika belum ada Super Admin aktif.
    if not akun.is_super:
        raise HTTPException(403, 'Data perusahaan hanya tersedia untuk Super Admin.')
    return akun

@router.get('/pengaturan/perusahaan')
async def halaman(request:Request,akun=Depends(butuh_perusahaan)):
    async with SessionLocal() as db:data=await baca(db)
    return render(request,'perusahaan.html',layar='pengaturan',kembali='/pengaturan',
        perusahaan=data.data(),tersimpan=request.query_params.get('tersimpan')=='1',err='')

@router.post('/pengaturan/perusahaan')
async def ubah(request:Request,akun=Depends(butuh_perusahaan)):
    form=await request.form()
    data={k:str(form.get(k,'')) for k in ('nama','alamat','telepon','email','website')}
    unggahan=form.get('logo');raw=None
    try:
        if getattr(unggahan,'filename',None):raw=await unggahan.read(BATAS_LOGO+1)
        async with SessionLocal() as db:
            await simpan(db,data,logo=raw,logo_bawaan=form.get('logo_bawaan')=='1',user=akun.user)
    except ValueError as e:
        async with SessionLocal() as db:lama=await baca(db)
        return render(request,'perusahaan.html',layar='pengaturan',kembali='/pengaturan',
            perusahaan=dict(lama.data(),**data),tersimpan=False,err=str(e),status_code=422)
    return redirect('/pengaturan/perusahaan?tersimpan=1')
