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
    # Sama dengan tombol Pengiriman: Admin membaca; Super Admin dan
    # operator gudang aktif mencatat. Operator G1/G2 tetap saling menggantikan.
    from hmu_identitas import peran as P
    return P.super_saja(user.role) or (not can_see_financials(user) and
        (await _is_g1_operator(user) or await _is_g2_operator(user)))

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
        from app.web.selesai_muatan import papan_selesai
        data=await papan_selesai(db,perintah)
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

# Lembar kerja mengorkestrasi layanan lama. Satu transaksi memiliki seluruh
# perubahan; jalur per-item / muat-semua lama tetap memakai commit bawaannya.
from pydantic import BaseModel, ConfigDict, FiniteFloat
from types import SimpleNamespace
import hashlib
import hmac
import json
from app.web.security import _kunci


class KonteksLembar(BaseModel):
    model_config = ConfigDict(extra='forbid')
    perintah_id: int
    pelanggan_id: int | None
    dasar: str


class BarisLembar(BaseModel):
    model_config = ConfigDict(extra='forbid')
    perintah_id: int
    item_id: int
    jumlah: FiniteFloat


class LembarMuatReq(BaseModel):
    model_config = ConfigDict(extra='forbid')
    perintah_id: int
    kiriman_id: int | None
    konteks: list[KonteksLembar]
    barang: list[BarisLembar]
    selesaikan: list[int] = []
    pemeriksaan: str = ''


def _cap_lembar(user, rencana):
    isi = json.dumps([user.id, str(user.role), rencana], sort_keys=True,
                     separators=(',', ':'), ensure_ascii=False)
    return hmac.new(_kunci(), ('lembar-muat-v1:'+isi).encode(), hashlib.sha256).hexdigest()


async def rencana_lembar(db, req, user):
    """Tidak menulis aktual. Semua acuan diperiksa sebelum item pertama berubah."""
    await bk._kunci_saldo_keluar(db)
    anchor = await db.get(OutgoingRecord, req.perintah_id, populate_existing=True)
    if not anchor or anchor.kiriman_id != req.kiriman_id:
        raise HTTPException(400, 'Kiriman tidak sesuai dengan konteks lembar muatan.')
    anggota = await bk.anggota_kiriman(db, anchor, kunci=True)
    records = {r.id:r for r in anggota}
    konteks = {k.perintah_id:k for k in req.konteks}
    if len(konteks)!=len(req.konteks) or set(konteks)!=set(records):
        raise HTTPException(400, 'Daftar perintah tidak sesuai dengan seluruh kiriman.')
    items = list((await db.scalars(select(OutgoingItem).where(
        OutgoingItem.outgoing_record_id.in_(records)).order_by(OutgoingItem.id)
        .execution_options(populate_existing=True))).all())
    await bk._kunci_sumber_keluar(db, [bk.baris_dari_item(i) for i in items])
    snapshots = {}
    for rid, rec in records.items():
        ctx = konteks[rid]
        _wajib_periksa_muat(ctx.dasar)
        if rec.pelanggan_id != ctx.pelanggan_id:
            raise HTTPException(400, 'Penerima tidak sesuai dengan perintah pelanggan.')
        await bk._periksa_dasar_muat(db, rec, ctx.dasar)
        snapshots[rid] = await bk.ringkasan_muat(db, rec)
    pilihan = {b.item_id:b for b in req.barang}
    if len(pilihan)!=len(req.barang):
        raise HTTPException(400, 'Satu barang tidak boleh dicatat dua kali dalam lembar yang sama.')
    by_id = {i.id:i for i in items}
    urutan = []
    for iid, b in pilihan.items():
        it = by_id.get(iid)
        if not it or it.outgoing_record_id!=b.perintah_id or b.perintah_id not in records:
            raise HTTPException(400, 'Barang bukan bagian dari perintah/pelanggan kiriman ini.')
        await bk._kunci_muat(db, b.perintah_id, dasar=konteks[b.perintah_id].dasar)
        if b.jumlah <= 0:
            raise HTTPException(400, 'Total yang dicatat wajib positif, mengikuti aturan pencatatan muatan.')
        bag = it.item_type=='finished_goods'
        if bag and not float(b.jumlah).is_integer():
            raise HTTPException(400, 'Total yang sudah dimuat dalam karung wajib bilangan bulat.')
        berat, _ = await bk._berat_baris(db, bk.baris_dari_item(it,
            jumlah_karung=int(b.jumlah) if bag else None, berat_kg=None if bag else b.jumlah))
        # Pemulihan sah dijalankan lebih dahulu agar stok bebas hasil koreksi
        # dapat dipakai baris lain, dengan kunci sumber yang sama.
        urutan.append((berat-float(it.berat_kg or 0), iid, bag))
    dipakai = {}; baris = []; sumber = {}; efektif = {}
    for _, iid, bag in sorted(urutan):
        it = by_id[iid]; b = pilihan[iid]
        d = await bk.dampak_total_muatan(db, it,
            jumlah_karung=int(b.jumlah) if bag else None,
            berat_kg=None if bag else b.jumlah, terpakai=dipakai)
        snap = next(x for x in snapshots[b.perintah_id]['baris'] if x['id']==iid)
        d.update(perintah_id=b.perintah_id, pelanggan=records[b.perintah_id].nama_pembeli,
                 kode=records[b.perintah_id].kode, nama=snap['nama_lengkap'])
        efektif[iid] = d['berat_kg']
        # Tidak membuat audit/no-op baru pada total yang tidak berubah.
        if d['jumlah']==d['sebelumnya']: continue
        baris.append(d)
        key = bk._sumber_muatan(bk.baris_dari_item(it))
        if key not in sumber:
            sumber[key] = dict(nama=d['nama'], stok_sebelum_kg=d['stok_sebelum_kg'],
                stok_sesudah_kg=d['stok_sesudah_kg'], selisih_kg=0, pelanggan=[])
        src=sumber[key]; src['stok_sesudah_kg']=d['stok_sesudah_kg'];src['selisih_kg']+=d['selisih_kg']
        if b.perintah_id not in [p['id'] for p in src['pelanggan']]:
            src['pelanggan'].append(dict(id=b.perintah_id,nama=records[b.perintah_id].nama_pembeli))
    eligible=[]
    for rid, rec in records.items():
        calon=[SimpleNamespace(berat_perintah_kg=i.berat_perintah_kg,
            berat_kg=efektif.get(i.id,float(i.berat_kg or 0))) for i in items if i.outgoing_record_id==rid]
        syarat=bk.syarat_selesai_muat(calon)
        if rec.status=='perintah' and syarat['ada_muatan'] and not syarat['alasan_wajib']:
            eligible.append(dict(id=rid,nama=rec.nama_pembeli,kode=rec.kode))
    delta=sum(b['selisih_kg'] for b in baris)
    plan=dict(kiriman_id=anchor.kiriman_id,perintah_id=anchor.id,plat=anchor.no_polisi,
        tiket_id=anchor.timbangan_transaksi_id,baris=baris,sumber=list(sumber.values()),
        konteks=[k.model_dump() for k in sorted(req.konteks,key=lambda k:k.perintah_id)],
        bisa_selesai=eligible,selisih_kg=delta,
        total_armada_sebelum_kg=snapshots[anchor.id]['total_armada_kg'],
        total_armada_sesudah_kg=snapshots[anchor.id]['total_armada_kg']+delta)
    return plan, records


@router.post('/api/actions/periksa-lembar-muatan')
async def periksa_lembar(req:LembarMuatReq,user:User=Depends(pengguna_aksi)):
    wajib(await boleh_catat(user))
    async with SessionLocal() as db:
        try:
            plan,_=await rencana_lembar(db,req,user)
            return dict(rencana=plan,pemeriksaan=_cap_lembar(user,plan))
        except bk.BarangKeluarError as e:
            raise _galat_muatan(e,'Tidak bisa memeriksa perubahan muatan.')


@router.post('/api/actions/simpan-lembar-muatan')
async def simpan_lembar(req:LembarMuatReq,user:User=Depends(pengguna_aksi)):
    wajib(await boleh_catat(user))
    async with SessionLocal() as db:
        try:
            plan,records=await rencana_lembar(db,req,user)
            if not req.pemeriksaan or not hmac.compare_digest(req.pemeriksaan,_cap_lembar(user,plan)):
                raise HTTPException(409,'Ringkasan berubah atau belum diperiksa. Baca data terbaru lalu konfirmasi ulang.')
            eligible={p['id'] for p in plan['bisa_selesai']}
            if len(req.selesaikan)!=len(set(req.selesaikan)) or not set(req.selesaikan)<=eligible:
                raise HTTPException(400,'Pelanggan yang dipilih belum memenuhi syarat selesai muat sesuai perintah.')
            if not plan['baris'] and not req.selesaikan:
                raise HTTPException(400,'Tidak ada perubahan muatan atau penyelesaian yang dipilih.')
            u=await db.get(User,user.id)
            # Seluruh snapshot telah cocok di bawah kunci, sebelum mutasi.
            # Pemeriksaan ulang per item tetap melalui layanan lama; commit
            # ditunda agar audit, stok turunan, dan penutupan berhasil bersama.
            for d in plan['baris']:
                await bk.catat_muatan(db,user=u,item_id=d['id'],rec_id=d['perintah_id'],
                    jumlah_karung=d['jumlah_karung'],
                    berat_kg=None if d['satuan']=='karung' else d['berat_kg'],simpan=False)
            for rid in req.selesaikan:
                await bk.selesai_muat(db,user=u,rec_id=rid,simpan=False)
            await db.commit()
            return dict(ok=True,pesan='Perubahan muatan tercatat. Penyelesaian hanya berlaku pada pelanggan yang dipilih.',
                item_tersimpan=[d['id'] for d in plan['baris']],pelanggan_selesai=req.selesaikan)
        except bk.BarangKeluarError as e:
            await db.rollback()
            raise _galat_muatan(e,'Perubahan muatan tidak dapat dicatat.')
        except Exception:
            await db.rollback()
            raise
