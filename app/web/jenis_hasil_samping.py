"""Pengaturan hasil samping untuk Admin dan Super Admin."""
from fastapi import APIRouter, Depends, HTTPException, Request
from app.database import SessionLocal
from app.services import jenis_hasil_samping as master
from app.web.security import butuh_admin
from app.web.tampilan import redirect, render_laci

router = APIRouter(tags=['webapp'])
ALAMAT = '/pengaturan/hasil-samping'

async def halaman(request, *, err='', isian=None):
    async with SessionLocal() as db:
        daftar = await master.rincian(db)
    return await render_laci(request, 'jenis_hasil_samping.html', layar='pengaturan',
        kembali='/pengaturan', daftar=daftar, err=err, isian=isian or {},
        berhasil=request.query_params.get('berhasil') in {'tambah','ubah','hapus','nonaktifkan','aktifkan'})

@router.get(ALAMAT)
async def lihat(request: Request, akun=Depends(butuh_admin)):
    from app.web.pengaturan_master_kerangka import permintaan_kerangka,kerangka
    if permintaan_kerangka(request):
        from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
        context=await konteks_kerangka(request,akun)
        context['SHELL']={'data_url':request.url.path,'stamp':penanda_konteks(request,akun)+'|'+request.url.path}
        response=await kerangka(request,akun,context)
        if response is not None:return response
    return await halaman(request)

@router.post(ALAMAT + '/{aksi}')
async def ubah(aksi: str, request: Request, akun=Depends(butuh_admin)):
    if aksi not in {'tambah','ubah','hapus','nonaktifkan','aktifkan'}:
        raise HTTPException(404)
    data = dict(await request.form())
    try:
        async with SessionLocal() as db:
            await master.simpan(db, user=akun.user, aksi=aksi, kode=data.get('kode',''),
                versi=data.get('versi',''), nama=data.get('nama',''),
                bentuk=data.get('bentuk',''), kg_karung=data.get('kg_karung',''))
            await db.commit()
    except ValueError as e:
        return await halaman(request, err=str(e), isian={**data, 'aksi': aksi})
    return redirect(ALAMAT + '?berhasil=' + aksi)
