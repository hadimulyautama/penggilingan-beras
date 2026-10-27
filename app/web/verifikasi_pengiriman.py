"""Tampilan verifikasi; baca lewat pratinjau-muat dan tulis lewat endpoint lama."""
from fastapi import APIRouter,Depends,Request,HTTPException
from fastapi.encoders import jsonable_encoder
from app.database import SessionLocal
from app.models import OutgoingRecord
from app.services import barang_keluar as bk
from app.services import pemeriksaan_pengiriman as pemeriksaan
from app.peran import can_see_financials
from app.web.aksi_umum import wajib
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
from app.web.selesai_muatan import papan_selesai

router=APIRouter()

async def baca(db,perintah):
    rec=await db.get(OutgoingRecord,perintah)
    if not rec:raise HTTPException(404,'Perintah pengiriman tidak ditemukan.')
    # Kedua proyeksi memegang kunci saldo lama sampai seluruh halaman selesai
    # dibaca. Tidak memanggil auto_tautkan maupun transaksi verifikasi.
    await bk._kunci_saldo_keluar(db)
    kelompok=(await papan_selesai(db,perintah))['kiriman'][0]
    data=await pemeriksaan.baca(db,rec)
    data['pelanggan']=kelompok['pelanggan'];data['plat']=kelompok['plat']
    data['jumlah_pelanggan']=kelompok['jumlah_pelanggan'];data['pelanggan_selesai']=kelompok['pelanggan_selesai']
    data['jumlah_item']=sum(len(p['barang']) for p in data['pelanggan'] if p['status']!='batal')
    return data


@router.get('/verifikasi-pengiriman')
@router.get('/barang-keluar/{perintah:int}/verifikasi')
async def halaman(request:Request,perintah:int|None=None,akun=Depends(butuh_akun)):
    wajib(can_see_financials(akun.user))
    async with SessionLocal() as db:
        if perintah is not None:data=[await baca(db,perintah)]
        else:
            data=[];seen=set()
            for r,_ in await bk.daftar(db,status=('dimuat',),batas=500):
                key=('k',r.kiriman_id) if r.kiriman_id else ('p',r.id)
                if key in seen:continue
                seen.add(key);data.append(await baca(db,r.id))
    return await render_laci(request,'verifikasi_pengiriman.html',awal=jsonable_encoder(data),perintah=perintah)
