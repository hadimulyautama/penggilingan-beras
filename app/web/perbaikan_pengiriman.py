"""Pintu perbaikan pengiriman; mutasi tetap melalui layanan rantai lama.

Pembacaan tidak menjalankan undo. Log yang dikonfirmasi terikat pada
perintah asal; perubahan audit setelah pemeriksaan selalu memerlukan ulang.
"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ActivityLog, OutgoingItem, OutgoingRecord, User
from app.peran import can_see_financials
from app.services import barang_keluar as bk, undo
from app.web.aksi_umum import wajib
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()
LANGKAH = {
    'barang_keluar_verifikasi': 'Buka kembali verifikasi kiriman',
    'barang_keluar_muat': 'Batalkan langkah selesai muat',
    'barang_keluar_muat_baris': 'Batalkan pencatatan muatan terakhir',
}


async def konteks(db, identitas):
    rec = await db.get(OutgoingRecord, identitas)
    if rec is None:
        raise HTTPException(404, 'Pengiriman tidak ditemukan.')
    from app.web.riwayat_kiriman import baca
    data = await baca(db, rec, boleh_retur=True)
    ids = [p['rec'].id for p in data['pelanggan']]
    items = list((await db.scalars(select(OutgoingItem).where(
        OutgoingItem.outgoing_record_id.in_(ids)))).all())
    jasa = {i.outgoing_record_id for i in items if i.jasa_id}
    for p in data['pelanggan']:
        p['jasa'] = bool(p['rec'].jasa_id) or p['rec'].id in jasa
    return data


async def langkah_terakhir(db, data):
    # Cakupan "semua" sama dengan fasilitas undo Admin yang sudah berlaku.
    # Jangan mengganti dengan log terakhir per perintah: itu melonggarkan aturan.
    log = await undo._log_terakhir(db, None)
    ids = {p['rec'].id for p in data['pelanggan']}
    if not log or log.table_name != 'outgoing_records' or log.record_id not in ids or log.aksi not in LANGKAH:
        return dict(log=None, sebab='Tidak ada langkah muat/verifikasi kiriman ini yang merupakan input terakhir. Buka jejak audit untuk memeriksa urutan tindakan.')
    sebab = await undo.sebab_terkunci(db, log)
    return dict(log=log, sebab=sebab, label=LANGKAH[log.aksi],
                bersama=log.aksi == 'barang_keluar_verifikasi' and bool(data['rec'].kiriman_id))


@router.get('/barang-keluar/{identitas:int}/perbaikan')
async def halaman(request: Request, identitas: int, akun=Depends(butuh_akun)):
    wajib(can_see_financials(akun.user))
    async with SessionLocal() as db:
        data = await konteks(db, identitas)
        langkah = await langkah_terakhir(db, data)
    # Hanya parameter daftar yang diteruskan; tidak menerima URL kembali bebas.
    query = urlencode({k: request.query_params[k] for k in ('q', 'status', 'sejak', 'sebelum') if k in request.query_params})
    return await render_laci(request, 'perbaikan_pengiriman.html', perjalanan=data,
                            langkah=langkah, filter_query=query)


class BukaUlang(BaseModel):
    log_id: int
    alasan: str
    konfirmasi: bool = False


@router.post('/api/actions/perbaikan-pengiriman/{identitas:int}/buka-ulang')
async def buka_ulang(identitas: int, req: BukaUlang, user: User = Depends(pengguna_aksi)):
    wajib(can_see_financials(user))
    if not req.konfirmasi or not req.alasan.strip():
        raise HTTPException(400, 'Alasan dan konfirmasi pemeriksaan wajib diisi.')
    async with SessionLocal() as db:
        await bk._kunci_saldo_keluar(db)
        data = await konteks(db, identitas)
        log = await db.get(ActivityLog, req.log_id)
        ids = {p['rec'].id for p in data['pelanggan']}
        if not log or log.table_name != 'outgoing_records' or log.record_id not in ids or log.aksi not in LANGKAH:
            raise HTTPException(409, 'Langkah itu bukan bagian muat/verifikasi kiriman ini. Periksa ulang riwayat.')
        try:
            pesan = await undo.undo_last(db, actor=await db.get(User, user.id),
                cakupan=None, log_id=req.log_id, alasan=req.alasan.strip())
        except undo.UndoError as e:
            raise HTTPException(409, str(e)) from e
    return dict(ok=True, pesan=pesan, tujuan=f'/barang-keluar/{identitas}/perbaikan')
