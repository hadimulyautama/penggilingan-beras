"""Halaman perintah baru; simpan draf tanpa menyentuh stok atau antrean."""
import hashlib
import json
import math
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text
from app.database import SessionLocal
from app.models import DrafKeluar, User
from app.peran import can_see_financials
from app.services import barang_keluar as bk
from app.web.aksi_inventory import PerintahKeluarReq, _baris_dari_borang, _pelanggan_id, _id
from app.web.aksi_umum import wajib
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()

class SimpanDraf(BaseModel):
    revisi: int = Field(ge=0)
    kiriman: UUID
    isi: dict

class TerbitDraf(BaseModel):
    revisi: int = Field(ge=0)

async def _kunci(db, identitas):
    # Termasuk pembuatan pertama, ketika SELECT FOR UPDATE belum punya baris.
    if db.bind.dialect.name == 'postgresql':
        await db.execute(text('SELECT pg_advisory_xact_lock(:k)'),
                         {'k': int.from_bytes(hashlib.sha256(str(identitas).encode()).digest()[:8], 'big', signed=True)})

async def _ambil(db, identitas, user, *, termasuk_dihapus=False):
    d = await db.scalar(select(DrafKeluar).where(DrafKeluar.id == str(identitas)).with_for_update())
    if d and d.pemilik_id != user.id:
        raise HTTPException(404, 'Draf tidak ditemukan untuk akun ini.')
    if d and d.dihapus_pada and not termasuk_dihapus:
        raise HTTPException(404, 'Draf sudah dihapus. Isian di tab lama tidak akan disimpan kembali.')
    return d

def _hasil(d):
    return dict(revisi=d.revisi, isi=d.isi, tujuan=f'/barang-keluar/{d.perintah_id}' if d.perintah_id else None)

@router.get('/barang-keluar/baru')
@router.get('/barang-keluar/draf/{identitas}')
async def halaman(request: Request, identitas: UUID | None = None, akun=Depends(butuh_akun)):
    wajib(can_see_financials(akun.user))
    awal = dict(revisi=0, isi={})
    if identitas:
        async with SessionLocal() as db:
            d = await _ambil(db, identitas, akun.user)
            if not d:
                raise HTTPException(404, 'Draf belum tersimpan. Buka perintah baru.')
            if d.perintah_id:
                return RedirectResponse(f'/barang-keluar/{d.perintah_id}',303)
            awal = _hasil(d)
    return await render_laci(request, 'perintah_baru.html', draf_id=str(identitas or uuid4()), awal=awal)

@router.put('/api/actions/draf-perintah/{identitas}')
async def simpan(identitas: UUID, req: SimpanDraf, user: User = Depends(pengguna_aksi)):
    wajib(can_see_financials(user))
    try:
        serial = json.dumps(req.isi, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except ValueError:
        raise HTTPException(400, 'Draf mengandung angka yang tidak sah.')
    if len(serial.encode()) > 50_000:
        raise HTTPException(400, 'Draf terlalu besar. Maksimal 50 KB.')
    sidik = hashlib.sha256(serial.encode()).hexdigest()
    async with SessionLocal() as db:
        await _kunci(db, identitas)
        d = await _ambil(db, identitas, user)
        if d and d.perintah_id:
            raise HTTPException(409, dict(pesan='Perintah sudah diterbitkan. Buka detailnya.', **_hasil(d)))
        if d and d.kiriman == str(req.kiriman) and d.sidik == sidik:
            return _hasil(d)
        if (d.revisi if d else 0) != req.revisi:
            raise HTTPException(409, dict(pesan='Draf berubah di tab lain. Isian Anda tetap ada. Bandingkan dengan draf terbaru sebelum melanjutkan.', **_hasil(d)))
        if not d:
            d = DrafKeluar(id=str(identitas), pemilik_id=user.id, revisi=0, isi={})
            db.add(d)
        d.isi, d.revisi, d.kiriman, d.sidik = req.isi, req.revisi + 1, str(req.kiriman), sidik
        await db.commit()
        return _hasil(d)

@router.post('/api/actions/draf-perintah/{identitas}/terbitkan')
async def terbitkan(identitas: UUID, req: TerbitDraf, user: User = Depends(pengguna_aksi)):
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        await _kunci(db, identitas)
        d = await _ambil(db, identitas, user)
        if not d:
            raise HTTPException(400, 'Draf belum tersimpan. Tunggu hingga Tersimpan.')
        if d.perintah_id:
            return _hasil(d)
        if d.revisi != req.revisi:
            raise HTTPException(409, dict(pesan='Draf berubah. Periksa ulang sebelum menerbitkan.', **_hasil(d)))
        try:
            isi = PerintahKeluarReq.model_validate(d.isi)
            if not isi.barang or len(isi.barang) > 100 or any(not b.pilih or b.jumlah is None for b in isi.barang):
                raise HTTPException(400, 'Pilih barang dan isi jumlah pada setiap baris.')
            for b in isi.barang:
                if not math.isfinite(b.jumlah) or b.jumlah <= 0 or (b.pilih.startswith("bj:") and b.jumlah != int(b.jumlah)):
                    raise HTTPException(400, "Jumlah harus positif; karung wajib bilangan bulat.")
            baris = await _baris_dari_borang(db, isi)
            hasil = await bk.buat_perintah(db, user=await db.get(User,user.id), baris=baris,
                pelanggan_id=_pelanggan_id(isi.pelanggan), metode=isi.metode,
                tiket_armada_id=_id(isi.tiket_armada) if isi.tiket_armada else None,
                nama_ekspedisi=isi.nama_ekspedisi or None, simpan=False)
        except ValidationError:
            raise HTTPException(400, 'Periksa pilihan barang dan jumlah. Karung harus bilangan bulat positif.')
        except bk.BarangKeluarError as e:
            raise HTTPException(400, str(e))
        d.perintah_id = hasil.rec.id
        await db.commit()
        return _hasil(d)


async def daftar_draf(db, user):
    """Draf pribadi yang belum terbit, dibaca tanpa mengubah status atau stok."""
    from app.models import Pelanggan
    ds=list((await db.scalars(select(DrafKeluar).where(
        DrafKeluar.pemilik_id==user.id,DrafKeluar.perintah_id.is_(None),
        DrafKeluar.dihapus_pada.is_(None)).order_by(DrafKeluar.diperbarui.desc(),DrafKeluar.id))).all())
    ids={int(str(d.isi.get('pelanggan'))) for d in ds if str(d.isi.get('pelanggan','')).isdigit()}
    nama=dict((await db.execute(select(Pelanggan.id,Pelanggan.nama_pelanggan).where(Pelanggan.id.in_(ids)))).all()) if ids else {}
    hasil=[]
    for d in ds:
        pid=str(d.isi.get('pelanggan',''))
        pembeli=nama.get(int(pid)) if pid.isdigit() else None
        teks=d.isi.get('pelanggan_teks')
        pembeli=pembeli or (str(teks)+' (belum dipilih)' if teks else 'Pelanggan belum dipilih')
        barang=d.isi.get('barang')
        jumlah=sum(1 for b in barang if isinstance(b,dict) and (b.get('pilih') or b.get('jumlah'))) if isinstance(barang,list) else 0
        hasil.append(dict(id=d.id,revisi=d.revisi,pelanggan=pembeli,jumlah=jumlah,waktu=d.diperbarui))
    return hasil


@router.post('/api/actions/draf-perintah/{identitas}/hapus')
async def hapus(identitas: UUID, req: TerbitDraf, user: User = Depends(pengguna_aksi)):
    wajib(can_see_financials(user))
    from app.database import now_local
    async with SessionLocal() as db:
        await _kunci(db,identitas)
        d=await _ambil(db,identitas,user,termasuk_dihapus=True)
        if not d:
            raise HTTPException(404,'Draf tidak ditemukan.')
        if d.perintah_id:
            raise HTTPException(409,'Draf sudah diterbitkan. Periksa detail perintah; hapus draf tidak membatalkan perintah.')
        if d.dihapus_pada:
            return {'ok':True}
        if d.revisi!=req.revisi:
            raise HTTPException(409,'Draf berubah di tab lain. Muat ulang daftar dan periksa sebelum menghapus.')
        d.dihapus_pada=now_local()
        await db.commit()
        return {'ok':True}
