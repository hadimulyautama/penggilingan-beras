"""Pengaturan jenis beras, mengikuti peran efektif sesi."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.services import spesifikasi_beras as master
from app.web.security import butuh_admin
from app.web.tampilan import redirect, render_laci

router = APIRouter(tags=['webapp'])
ALAMAT = '/pengaturan/spesifikasi-beras'


async def halaman(request, *, err='', isian=None):
    async with SessionLocal() as db:
        daftar = await master.rincian(db, pemakaian=True)
    return await render_laci(request, 'spesifikasi_beras.html', layar='pengaturan',
        kembali='/pengaturan', daftar=daftar, err=err, isian=isian or {},
        berhasil=request.query_params.get('berhasil') in {'tambah', 'ubah', 'hapus', 'nonaktifkan', 'aktifkan', 'bawaan'})


@router.get(ALAMAT)
async def lihat(request: Request, akun=Depends(butuh_admin)):
    return await halaman(request)


@router.post(ALAMAT + '/{aksi}')
async def ubah(aksi: str, request: Request, akun=Depends(butuh_admin)):
    if aksi not in {'tambah', 'ubah', 'hapus', 'nonaktifkan', 'aktifkan', 'bawaan'}:
        raise HTTPException(404)
    data = dict(await request.form())
    try:
        id_ = int(data.get('id', '')) if aksi != 'tambah' else None
        async with SessionLocal() as db:
            await master.simpan(db, user=akun.user, id_=id_, versi=data.get('versi', ''),
                nama=data.get('nama', ''), broken=data.get('broken', ''),
                sosoh=data.get('sosoh', ''), aksi=aksi)
            await db.commit()
    except ValueError as e:
        return await halaman(request, err=str(e), isian={**data, 'aksi': aksi})
    except IntegrityError:
        return await halaman(request, err='Spesifikasi sudah dipakai atau berubah. Muat ulang halaman.',
                             isian={**data, 'aksi': aksi})
    return redirect(ALAMAT + '?berhasil=' + aksi)
