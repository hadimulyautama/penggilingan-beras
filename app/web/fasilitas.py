"""Pengaturan fasilitas: satu detail per line/mesin, sumber konfigurasi tetap sama."""
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import Warehouse, Dryer, JenisProsesProduksi, LiniProduksi
from app.services.fasilitas import simpan_jenis, simpan_lini, FasilitasError, PENJALAN
from app.web.security import butuh_super
from app.web.tampilan import render_laci, redirect

router = APIRouter()

async def halaman(request, akun, *, err='', form=None, mode=None, identitas=None, pesan='', pengering_id=None):
    mode = mode or ('jenis' if request.url.path.endswith('/jenis-proses') else 'mesin')
    async with SessionLocal() as db:
        jenis = list((await db.scalars(select(JenisProsesProduksi).order_by(JenisProsesProduksi.id))).all())
        lini = list((await db.scalars(select(LiniProduksi).order_by(LiniProduksi.warehouse_id, LiniProduksi.id))).all())
        gudang = list((await db.scalars(select(Warehouse).order_by(Warehouse.id))).all())
        dryer = list((await db.scalars(select(Dryer).order_by(Dryer.id))).all())
        from app.services.setelan import target_kadar_air
        from app.services.alur_beranda import peta_tungku
        target_global = await target_kadar_air(db)
        tungku = await peta_tungku(db)
    detail = next((l for l in lini if l.id == identitas), None) if identitas else None
    # Dryer historis yang belum bertaut line tetap mempunyai pintu yang jelas.
    did = pengering_id or request.path_params.get('dryer_id')
    pengering = next((d for d in dryer if d.id == (detail.dryer_id if detail else did)), None)
    if identitas and not detail or did and not pengering:
        raise HTTPException(404, 'Mesin/line tidak ditemukan.')
    if not pesan and request.query_params.get('pesan'):
        from app.web.pengaturan import _PESAN
        pesan = _PESAN.get(request.query_params['pesan'], '')
    return await render_laci(request, 'fasilitas.html', layar='pengaturan',
        kembali='/pengaturan/mesin' if detail or pengering else '/pengaturan',
        jenis=jenis, lini=lini, gudang=gudang, dryer=dryer, penjalan=PENJALAN,
        dryer_nama={d.id:d.nama for d in dryer}, jenis_nama={j.id:j.nama for j in jenis}, gudang_nama={w.id:w.nama_gudang for w in gudang},
        detail=detail, pengering=pengering, target_global=target_global, tungku=tungku,
        mode=mode, err=err, pesan=pesan, isian=form or {})

@router.get('/pengaturan/fasilitas')
async def lama(request: Request, akun=Depends(butuh_super)):
    # Bookmark lama tetap sampai ke pengelolaan yang sama, bukan konfigurasi kedua.
    return redirect('/pengaturan/mesin' + ('?tersimpan=1' if request.query_params.get('tersimpan') else ''))

@router.get('/pengaturan/mesin')
@router.get('/pengaturan/jenis-proses')
async def daftar(request: Request, akun=Depends(butuh_super)):
    return await halaman(request, akun)

@router.get('/pengaturan/mesin/{lini_id:int}')
async def detail_mesin(request: Request, lini_id: int, akun=Depends(butuh_super)):
    return await halaman(request, akun, identitas=lini_id)

@router.get('/pengaturan/dryer/{dryer_id:int}')
async def detail_dryer(request: Request, dryer_id: int, akun=Depends(butuh_super)):
    async with SessionLocal() as db:
        lid = await db.scalar(select(LiniProduksi.id).where(LiniProduksi.dryer_id == dryer_id))
    if lid:
        return redirect(f'/pengaturan/mesin/{lid}')
    return await halaman(request, akun)

async def tujuan(form):
    """Hanya tujuan lokal milik Pengaturan; tidak menerima open redirect."""
    import re
    nilai = form.get('kembali_pengaturan', '')
    if nilai in ('/pengaturan/mesin', '/pengaturan/jenis-proses', '/pengaturan/silo') or re.fullmatch(r'/pengaturan/(mesin|dryer)/[1-9][0-9]*', nilai):
        return nilai
    return '/pengaturan/jenis-proses' if form.get('objek') == 'jenis' else '/pengaturan/mesin'

@router.post('/pengaturan/fasilitas')
async def simpan(request: Request, akun=Depends(butuh_super)):
    form = dict(await request.form())
    try:
        def angka(k):
            return int(form[k]) if form.get(k) else None
        data = dict(user=akun.user, nama=form.get('nama', ''), kode=form.get('kode', ''),
                    aktif=form.get('aktif') == 'on', id=angka('id'), versi=angka('versi'))
        async with SessionLocal() as db:
            if form.get('objek') == 'jenis':
                await simpan_jenis(db, **data)
            elif form.get('objek') == 'lini':
                await simpan_lini(db, **data, warehouse_id=angka('warehouse_id'),
                    jenis_proses_id=angka('jenis_proses_id'), dryer_id=angka('dryer_id'))
            else:
                raise FasilitasError('Tindakan tidak dikenal.')
            await db.commit()
    except (FasilitasError, ValueError, IntegrityError) as exc:
        err = 'Data telah berubah atau kode sudah digunakan. Periksa kembali.' if isinstance(exc, IntegrityError) else str(exc)
        return await halaman(request, akun, err=err, form=form,
            mode='jenis' if form.get('objek') == 'jenis' else 'mesin',
            identitas=int(form['id']) if form.get('objek') == 'lini' and form.get('id', '').isdigit() else None)
    return redirect(await tujuan(form) + '?tersimpan=1')
