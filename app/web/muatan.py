"""Daftar dan pratinjau Catat muatan; penulisan tetap pada endpoint lama."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from app.database import SessionLocal
from app.models import OutgoingRecord, OutgoingItem, User
from app.services import barang_keluar as bk
from app.peran import can_see_financials
from app.web.api import _is_g1_operator, _is_g2_operator
from app.web.aksi_inventory import MuatBarisReq, _id, _galat_muatan, _wajib_periksa_muat, _periksa_konteks_muat
from app.web.aksi_umum import wajib
from app.web.deps import pengguna_aksi
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router=APIRouter()

async def boleh_catat(user):
    # Sama dengan kedua endpoint tulis lama; tidak menyaring gudang sumber.
    return await _is_g1_operator(user) or await _is_g2_operator(user)

async def papan(db, perintah=None):
    await bk._kunci_saldo_keluar(db)
    if perintah is not None:
        rec=await db.get(OutgoingRecord,perintah)
        if not rec:raise HTTPException(404,'Perintah muat tidak ditemukan.')
        calon=[rec]
    else:
        calon=[r for r,_ in await bk.daftar(db,status=('perintah','dimuat'),batas=500)]
    hasil=[];dilihat=set()
    for rec in calon:
        kunci=('kiriman',rec.kiriman_id) if rec.kiriman_id else ('perintah',rec.id)
        if kunci in dilihat:continue
        dilihat.add(kunci)
        anggota=await bk.anggota_kiriman(db,rec)
        pelanggan=[]
        for r in anggota:
            snap=await bk.ringkasan_muat(db,r)
            rows=snap['baris']
            pelanggan.append(dict(id=r.id,kode=r.kode,pelanggan_id=r.pelanggan_id,
                nama=r.nama_pembeli or 'Pelanggan belum tercatat',status=r.status,dasar=snap['dasar'],
                barang=rows,total_perintah_kg=sum(b['perintah_kg'] for b in rows),
                total_dimuat_kg=sum(b['dimuat_kg'] for b in rows),
                total_sisa_kg=sum(b['sisa_kg'] for b in rows)))
        aktif=[p for p in pelanggan if p['status']!='batal']
        status=('Sedang dimuat' if any(p['status']=='perintah' for p in aktif) else
                'Selesai muat · menunggu verifikasi' if any(p['status']=='dimuat' for p in aktif) else
                'Terverifikasi' if aktif else 'Dibatalkan')
        tiket=None
        if rec.timbangan_transaksi_id:
            t=(await db.execute(text('SELECT id,kode,status_tiket FROM timbangan_transaksi WHERE id=:id'),
                {'id':rec.timbangan_transaksi_id})).mappings().first()
            if t:tiket=dict(t)
        hasil.append(dict(id=rec.kiriman_id,kunci=':'.join(map(str,kunci)),perintah_id=rec.id,
            plat=rec.no_polisi,tiket=tiket,status=status,pelanggan=pelanggan,
            total_perintah_kg=sum(p['total_perintah_kg'] for p in aktif),
            total_dimuat_kg=sum(p['total_dimuat_kg'] for p in aktif),
            total_sisa_kg=sum(p['total_sisa_kg'] for p in aktif)))
    return {'kiriman':hasil}

@router.get('/muatan')
@router.get('/barang-keluar/{perintah:int}/muatan')
async def halaman(request:Request,perintah:int|None=None,akun=Depends(butuh_akun)):
    boleh=await boleh_catat(akun.user)
    wajib(boleh or can_see_financials(akun.user))
    async with SessionLocal() as db:
        data=await papan(db,perintah)
    return await render_laci(request,'catat_muatan.html',awal=data,boleh_catat=boleh,
        perintah=perintah,item_awal=request.query_params.get('item',''),
        semua_awal=request.query_params.get('semua',''))

@router.get('/api/actions/papan-muatan')
async def daftar(perintah:int|None=None,user:User=Depends(pengguna_aksi)):
    wajib(await boleh_catat(user) or can_see_financials(user))
    async with SessionLocal() as db:return await papan(db,perintah)

class PeriksaMuatReq(MuatBarisReq):
    semua:bool=False

@router.post('/api/actions/periksa-catat-muatan')
async def periksa(req:PeriksaMuatReq,user:User=Depends(pengguna_aksi)):
    wajib(await boleh_catat(user))
    _wajib_periksa_muat(req.dasar)
    async with SessionLocal() as db:
        try:
            rec=await bk._kunci_muat(db,_id(req.perintah),dasar=req.dasar)
            items=list((await db.scalars(select(OutgoingItem).where(
                OutgoingItem.outgoing_record_id==rec.id).order_by(OutgoingItem.id))).all())
            if not req.semua:
                items=[it for it in items if it.id==_id(req.baris)]
                if not items:raise HTTPException(400,'Barang itu bukan bagian dari perintah yang dipilih.')
            await bk._kunci_sumber_keluar(db,[bk.baris_dari_item(it) for it in items])
            await bk._periksa_dasar_muat(db,rec,req.dasar)
            _periksa_konteks_muat(req,rec)
            snap=await bk.ringkasan_muat(db,rec)
            rencana=[];dipakai={}
            for it in items:
                karung=it.item_type=='finished_goods'
                jumlah=it.jumlah_karung_perintah if req.semua else req.jumlah
                berat=float(it.berat_perintah_kg or 0) if req.semua else req.jumlah
                rencana.append(await bk.dampak_total_muatan(db,it,
                    jumlah_karung=jumlah if karung else None,berat_kg=None if karung else berat,
                    semua=req.semua,terpakai=dipakai))
            nama_baris={b['id']:b.get('nama_lengkap') or b['nama'] for b in snap['baris']}
            for d in rencana:d['nama']=nama_baris[d['id']]
            delta=sum(d['selisih_kg'] for d in rencana)
            return dict(perintah_id=rec.id,kode=rec.kode,kiriman_id=rec.kiriman_id,
                pelanggan_id=rec.pelanggan_id,pelanggan=rec.nama_pembeli,plat=rec.no_polisi,
                tiket_id=rec.timbangan_transaksi_id,dasar=snap['dasar'],semua=req.semua,
                baris=rencana,selisih_kg=delta,total_armada_sebelum_kg=snap['total_armada_kg'],
                total_armada_sesudah_kg=snap['total_armada_kg']+delta)
        except bk.BarangKeluarError as e:raise _galat_muatan(e,'Tidak bisa memeriksa pencatatan muatan.')
