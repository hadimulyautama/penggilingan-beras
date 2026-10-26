"""Pemeriksaan penyelesaian per pelanggan; penulisan tetap layanan Selesai muat."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from app.database import SessionLocal
from app.models import ActivityLog, OutgoingItem, OutgoingRecord, User
from app.peran import can_see_financials
from app.services import barang_keluar as bk
from app.web.aksi_inventory import (SelesaiMuatReq, _id, _galat_muatan,
    _periksa_konteks_muat, _periksa_item_selesai, _wajib_periksa_muat)
from app.web.aksi_umum import wajib
from app.web.deps import pengguna_aksi
from app.web.muatan import boleh_catat, papan
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router=APIRouter()


async def papan_selesai(db, perintah=None):
    data=await papan(db,perintah)
    ids=[p['id'] for k in data['kiriman'] for p in k['pelanggan']]
    items=list((await db.scalars(select(OutgoingItem).where(
        OutgoingItem.outgoing_record_id.in_(ids)).order_by(OutgoingItem.id))).all()) if ids else []
    records={r.id:r for r in (await db.scalars(select(OutgoingRecord).where(
        OutgoingRecord.id.in_(ids)))).all()} if ids else {}
    logs=list((await db.scalars(select(ActivityLog).where(
        ActivityLog.table_name=='outgoing_records',ActivityLog.record_id.in_(ids),
        ActivityLog.aksi=='barang_keluar_muat',ActivityLog.dibatalkan_pada.is_(None))
        .order_by(ActivityLog.id.desc()))).all()) if ids else []
    penutupan={}
    for log in logs:penutupan.setdefault(log.record_id,log)
    for k in data['kiriman']:
        for p in k['pelanggan']:
            baris=[i for i in items if i.outgoing_record_id==p['id']]
            syarat=bk.syarat_selesai_muat(baris)
            p.update(syarat)
            p['bisa_selesai']=p['status']=='perintah' and syarat['ada_muatan']
            p['penutupan']=None
            if p['status'] in ('dimuat','selesai'):
                r=records[p['id']];log=penutupan.get(p['id']);petugas=await db.get(User,r.dimuat_oleh) if r.dimuat_oleh else None
                p['penutupan']=dict(alasan=log.alasan_perubahan if log else None,
                    petugas=petugas.nama if petugas else None,
                    waktu=r.waktu_muat.isoformat() if r.waktu_muat else None,
                    log_id=log.id if log else None)
        aktif=[p for p in k['pelanggan'] if p['status']!='batal']
        selesai=sum(p['status'] in ('dimuat','selesai') for p in aktif)
        semua=bool(aktif) and selesai==len(aktif)
        verifikasi=bool(aktif) and all(p['status']=='selesai' for p in aktif)
        kesiapan=('dibatalkan' if not aktif else 'terverifikasi' if verifikasi else
            'menunggu_pelanggan' if not semua else 'menunggu_tiket' if not k['tiket'] else
            'menunggu_timbang_kedua' if k['tiket']['status_tiket']!='SELESAI' else 'menunggu_pemeriksaan')
        k.update(jumlah_pelanggan=len(aktif),pelanggan_selesai=selesai,
            semua_selesai_muat=semua,terverifikasi=verifikasi,kesiapan=kesiapan,
            total_tidak_terkirim_kg=sum(p['tidak_terkirim_kg'] for p in aktif if p['status'] in ('dimuat','selesai')))
    return data


@router.get('/selesai-muat')
@router.get('/barang-keluar/{perintah:int}/selesai-muat')
async def halaman(request:Request,perintah:int|None=None,akun=Depends(butuh_akun)):
    boleh=await boleh_catat(akun.user)
    wajib(boleh or can_see_financials(akun.user))
    async with SessionLocal() as db:data=await papan_selesai(db,perintah)
    return await render_laci(request,'selesai_muatan.html',awal=data,boleh_selesai=boleh,
        perintah=perintah,buka_awal=request.query_params.get('buka',''))


@router.get('/api/actions/papan-selesai-muat')
async def daftar(perintah:int|None=None,user:User=Depends(pengguna_aksi)):
    wajib(await boleh_catat(user) or can_see_financials(user))
    async with SessionLocal() as db:return await papan_selesai(db,perintah)


@router.post('/api/actions/periksa-selesai-muat')
async def periksa(req:SelesaiMuatReq,user:User=Depends(pengguna_aksi)):
    wajib(await boleh_catat(user))
    _wajib_periksa_muat(req.dasar)
    async with SessionLocal() as db:
        try:
            rec=await bk._kunci_muat(db,_id(req.perintah),dasar=req.dasar)
            await bk._periksa_dasar_muat(db,rec,req.dasar)
            _periksa_konteks_muat(req,rec)
            items=list((await db.scalars(select(OutgoingItem).where(
                OutgoingItem.outgoing_record_id==rec.id).order_by(OutgoingItem.id))).all())
            _periksa_item_selesai(req,items)
            syarat=bk.periksa_selesai_muat(rec,items,req.sebab)
            snap=await bk.ringkasan_muat(db,rec)
            return dict(perintah_id=rec.id,kiriman_id=rec.kiriman_id,pelanggan_id=rec.pelanggan_id,
                kode=rec.kode,pelanggan=rec.nama_pembeli,plat=rec.no_polisi,
                tiket_id=rec.timbangan_transaksi_id,dasar=snap['dasar'],barang=snap['baris'],
                total_perintah_kg=sum(float(i.berat_perintah_kg or 0) for i in items),
                total_aktual_kg=sum(float(i.berat_kg or 0) for i in items),
                tidak_terkirim_kg=syarat['tidak_terkirim_kg'],alasan=req.sebab.strip(),
                total_armada_kg=snap['total_armada_kg'],perubahan_stok_kg=0)
        except bk.BarangKeluarError as e:raise _galat_muatan(e,'Tidak bisa memeriksa penyelesaian muatan.')
