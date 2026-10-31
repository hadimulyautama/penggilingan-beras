"""Koreksi pascaverifikasi, tanpa undo atau batas umur.

Audit tambah-saja menyimpan sebelum/sesudah. OutgoingItem adalah proyeksi
efektif yang sudah dibaca seluruh mesin stok/retur/dokumen lama, sehingga
tidak ada ledger pengurangan kedua. Snapshot sumber awal selalu tersimpan;
penggantian sumber ditahan bila identitas item sudah dipakai oleh retur.
Tidak commit; transaksi dimiliki endpoint.
"""
from dataclasses import replace
from decimal import Decimal as D
import hashlib
import hmac
import json
import re

from sqlalchemy import case, func, select, text
from app.database import now_local
from app.models import (ActivityLog, CustomerReturnItem, Jasa,
                        KoreksiPengiriman, OutgoingItem, OutgoingRecord, ProductSku)
from app.penggilingan.inventory.models import ReturRincian
from app.peran import can_see_financials
from app.services import barang_keluar as bk, retur_pengajuan as retur
from app.services.activity_log import log_activity
from app.services.pilihan_barang_keluar import urai
from app.services.retur import angka

SUMBER = ('item_type','product_sku_id','rice_quality_standard_id','jenis_byproduct',
          'milling_process_id','silo_id','gabah_kering_lot_id','jasa_id')
ANGKA = ('berat_kg','jumlah_karung','berat_perintah_kg','jumlah_karung_perintah')


def bersih(v):
    return json.loads(json.dumps(v, default=str, sort_keys=True))


def sidik(v):
    return hashlib.sha256(json.dumps(bersih(v),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def cap(v):
    from app.web.security import _kunci
    key=_kunci()
    return hmac.new(key.encode() if isinstance(key,str) else key,sidik(v).encode(),hashlib.sha256).hexdigest()


def izin(user):
    if not can_see_financials(user):
        raise PermissionError('Koreksi pengiriman hanya tersedia untuk Admin/Super Admin pada peran efektifnya.')


def item_snapshot(i):
    return dict(id=i.id,**{k:getattr(i,k) for k in SUMBER+ANGKA})


def sumber(b):
    return dict(item_type=b.tipe,product_sku_id=b.sku_id,rice_quality_standard_id=b.std_id,
        jenis_byproduct=b.jenis,milling_process_id=b.milling_process_id,silo_id=b.silo_id,
        gabah_kering_lot_id=b.gabah_kering_lot_id,jasa_id=b.jasa_id)


async def pilihan(db,i):
    if i.item_type=='finished_goods':v=f'bj:{i.product_sku_id}|{i.rice_quality_standard_id or ""}'
    elif i.item_type=='byproduct_curah':v='cr:'+i.jenis_byproduct
    elif i.item_type=='pk_g2':v='g2:tumpukan' if i.silo_id is None else f'g2:silo:{i.silo_id}'
    elif i.item_type=='pk_langsung':
        from app.models import MillingProcess
        p=await db.get(MillingProcess,i.milling_process_id);v='pk:'+p.kode_proses if p else ''
    elif i.item_type=='gabah_langsung':
        from app.models import GabahKeringLot
        p=await db.get(GabahKeringLot,i.gabah_kering_lot_id);v='gk:'+p.kode_lot if p else ''
    else:raise ValueError('Jenis barang historis belum mendukung koreksi. Data asal tetap dipertahankan.')
    return v+('@'+str(i.jasa_id) if i.jasa_id else '')


async def ambil(db,rid,user,*,kunci=False):
    izin(user)
    if kunci:await bk._kunci_saldo_keluar(db)
    rec=await db.scalar(select(OutgoingRecord).where(OutgoingRecord.id==rid).with_for_update().execution_options(populate_existing=True)) if kunci else await db.get(OutgoingRecord,rid)
    if not rec:raise ValueError('Pengiriman tidak ditemukan.')
    anggota=await bk.anggota_kiriman(db,rec,kunci=kunci)
    if not anggota or any(r.status!='selesai' for r in anggota if r.status!='batal') or rec.status!='selesai':
        raise ValueError('Koreksi ini hanya untuk kiriman yang seluruh pelanggan aktifnya sudah selesai diverifikasi.')
    if kunci:
        await db.refresh(rec)
    q=select(OutgoingItem).where(OutgoingItem.outgoing_record_id==rid).order_by(OutgoingItem.id).execution_options(populate_existing=True)
    items=list((await db.scalars(q.with_for_update() if kunci else q)).all())
    if not items:raise ValueError('Rincian pengiriman belum tersedia.')
    versi=await db.scalar(select(func.max(KoreksiPengiriman.versi)).where(KoreksiPengiriman.outgoing_record_id==rid)) or 0
    return rec,anggota,items,versi


async def data(db,rid,user):
    rec,anggota,items,versi=await ambil(db,rid,user)
    from app.web.layar_keluar import _nama_barang
    names=await _nama_barang(db,[(rec,items)])
    rows=[]
    for i in items:
        rows.append(dict(id=i.id,nama=names.get(i.id,'Barang historis'),pilih=await pilihan(db,i),
            jumlah=('' if i.jumlah_karung is None else str(i.jumlah_karung)) if i.item_type=='finished_goods' else str(i.berat_kg),
            satuan='karung' if i.item_type=='finished_goods' else 'kg',berat_kg=float(i.berat_kg)))
    logs=list((await db.scalars(select(KoreksiPengiriman).where(
        KoreksiPengiriman.outgoing_record_id==rid).order_by(KoreksiPengiriman.versi.desc()))).all())
    return dict(rec=rec,barang=rows,versi=versi,jasa=bool(rec.jasa_id or any(i.jasa_id for i in items)),
                anggota=anggota,koreksi=logs)


async def rencana(db,rid,user,req):
    rec,anggota,items,versi=await ambil(db,rid,user,kunci=True)
    if req.get('konfirmasi') is not True or not req.get('alasan','').strip():
        raise ValueError('Alasan dan konfirmasi pemeriksaan kesalahan pencatatan wajib diisi. Barang yang baru kembali harus melalui retur.')
    if len(req['alasan'])>2000:raise ValueError('Alasan maksimal 2.000 karakter.')
    raw=req.get('barang',[]);mapping={r['item_id']:r for r in raw}
    if len(mapping)!=len(raw) or set(mapping)!={i.id for i in items}:
        raise ValueError('Seluruh item harus sesuai perintah/pelanggan asal, tanpa duplikasi atau item pelanggan lain.')
    pid=req['pelanggan_id']
    if pid==rec.pelanggan_id:nama=rec.nama_pembeli
    else:nama,_=await bk._pembeli(db,pid)
    if rec.kiriman_id and any(r.id!=rec.id and r.pelanggan_id==pid for r in anggota):
        raise ValueError('Pelanggan tersebut sudah mempunyai kelompok dalam kiriman ini. Koreksi tidak boleh menggabungkan atau membuang item diam-diam.')
    _,pakai=await retur.sisa_asal(db,rid)
    has_return=bool(await db.scalar(select(ReturRincian.id).where(ReturRincian.outgoing_record_id==rid).limit(1))
        or await db.scalar(select(CustomerReturnItem.id).where(CustomerReturnItem.outgoing_item_id.in_([i.id for i in items])).limit(1)))
    if pid!=rec.pelanggan_id and has_return:
        raise ValueError('Pelanggan tidak dapat diganti karena terdapat jejak retur terkait. Selesaikan relasi tersebut melalui alur yang sah.')
    jasa=bool(rec.jasa_id or any(i.jasa_id for i in items))
    rows=[];bars=[];changed=pid!=rec.pelanggan_id
    for i in items:
        row=mapping[i.id];old=bk.baris_dari_item(i);pick=(row.get('pilih') or '').strip()
        same=not pick or pick==await pilihan(db,i)
        b=old if same else await urai(db,pick,1)
        value=row.get('jumlah')
        if value is None or isinstance(value,bool) or not str(value).strip():raise ValueError('Isi jumlah setiap barang; gunakan nol secara eksplisit jika tidak ikut keluar.')
        n=angka(value,'Jumlah yang benar',1_000_000,'1' if b.tipe=='finished_goods' else '.01')
        if not same and n==0:
            raise ValueError('Untuk barang yang tidak ikut keluar, nolkan jumlah pada sumber asal. Penggantian sumber memerlukan jumlah positif yang dapat diperiksa.')
        b=replace(b,jumlah_karung=int(n) if b.tipe=='finished_goods' else None,berat_kg=float(n) if b.tipe!='finished_goods' else None)
        owner_ids={v for v in (old.jasa_id,b.jasa_id) if v is not None}
        if owner_ids:
            await db.scalars(select(Jasa).where(Jasa.id.in_(owner_ids)).order_by(Jasa.id).with_for_update().execution_options(populate_existing=True))
        if bool(b.jasa_id)!=jasa:raise ValueError('Barang jasa dan penjualan pabrik tidak boleh dicampur atau dipindahkan kepemilikannya lewat koreksi.')
        if b.jasa_id:
            j=await db.get(Jasa,b.jasa_id)
            if not j or j.pelanggan_id!=pid:raise ValueError('Sumber jasa bukan milik pelanggan yang benar. Pilih barang dari pesanan pelanggan tersebut.')
            if not same and j.status!='berjalan':raise ValueError('Sumber pengganti harus berasal dari pesanan jasa yang masih berjalan.')
        if b.tipe=='finished_goods':
            from app.models import PackageSize
            sku=await db.scalar(select(ProductSku).where(ProductSku.id==b.sku_id).with_for_update().execution_options(populate_existing=True))
            if not sku:raise ValueError('SKU sumber tidak tersedia.')
            await db.scalar(select(PackageSize).where(PackageSize.id==sku.package_size_id).with_for_update().execution_options(populate_existing=True))
        kg,karung=await bk._berat_baris(db,b) if n>0 else (0,0 if b.tipe in ('finished_goods','pk_g2','pk_langsung') else None)
        if not D(str(kg)).is_finite() or kg<0 or n>0 and kg<=0:
            raise ValueError('Bobot hasil perhitungan sumber/kemasan belum sah; koreksi tidak dapat disimpan.')
        usage=pakai[i.id]
        if not same and (usage['kg']>0 or usage['karung']>0 or has_return):
            raise ValueError('Sumber/item tidak dapat diganti karena memiliki jejak retur. Identitas asal retur harus tetap utuh.')
        if D(str(kg))<usage['kg'] or b.tipe=='finished_goods' and n<usage['karung']:
            raise ValueError('Jumlah koreksi lebih kecil dari retur diterima dan pengajuan aktif item ini.')
        if (i.harga_per_kg is not None or i.total_harga is not None) and (not same or D(str(kg))!=D(i.berat_kg) or pid!=rec.pelanggan_id):
            raise ValueError('Item memiliki nilai penjualan tercatat. Koreksi relasi finansial harus ditangani melalui alur yang berwenang terlebih dahulu.')
        baru=dict(**sumber(b),berat_kg=kg,jumlah_karung=karung)
        if not same or D(str(kg))!=D(i.berat_kg) or karung!=i.jumlah_karung:changed=True
        rows.append(dict(item_id=i.id,pilih=pick or await pilihan(db,i),ganti_sumber=not same,
            sebelum=item_snapshot(i),sesudah=baru,retur=usage))
        bars.append((old,b))
    if not changed:raise ValueError('Belum ada perubahan jumlah, barang, atau pelanggan.')
    if not any(r['sesudah']['berat_kg']>0 for r in rows):raise ValueError('Minimal satu barang harus tetap tercatat keluar. Pembatalan fisik bukan koreksi jumlah nol seluruh pengiriman.')
    if sum(r['sesudah']['berat_kg']>0 for r in rows)>12:raise ValueError('Maksimal 12 barang aktif per perintah pelanggan mengikuti batas lama.')
    await bk._kunci_sumber_keluar(db,[b for pair in bars for b in pair])
    # Stok jadi dikunci juga, termasuk pemakaian ulang/kemas ulang pada baris
    # yang sama. Rumus fisik dan saldo bebas tetap berasal dari `tersedia`.
    from app.models import FinishedGoodsStock
    skus={b.sku_id for pair in bars for b in pair if b.sku_id}
    if skus:await db.scalars(select(FinishedGoodsStock).where(FinishedGoodsStock.product_sku_id.in_(skus)).order_by(FinishedGoodsStock.id).with_for_update())
    pools={}
    async def tambah(b,kg,karung=None):
        key=bk._sumber_muatan(b)
        if key not in pools:
            free,label=await bk.tersedia(db,b)
            physical,_=await bk.tersedia(db,b,abaikan_pesanan=True)
            if b.jasa_id:
                pesanan=await db.get(Jasa,b.jasa_id)
                label+=' · '+pesanan.kode
            pools[key]=dict(nama=label,sumber=sumber(b),gudang_fungsi=bk.GUDANG_ITEM.get(b.tipe),stok_kg=physical,bebas_kg=free,delta_kg=0.)
            if b.tipe=='finished_goods':
                from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
                stok=await hitung_stok_finished_goods(db,b.sku_id,b.std_id,jasa_id=b.jasa_id)
                sisa=func.coalesce(OutgoingItem.jumlah_karung_perintah,0)-func.coalesce(OutgoingItem.jumlah_karung,0)
                q=select(func.coalesce(func.sum(case((sisa<0,0),else_=sisa)),0)).join(OutgoingRecord,OutgoingRecord.id==OutgoingItem.outgoing_record_id).where(
                    OutgoingRecord.status=='perintah',OutgoingItem.item_type=='finished_goods',OutgoingItem.product_sku_id==b.sku_id,
                    OutgoingItem.rice_quality_standard_id==b.std_id,OutgoingItem.jasa_id==b.jasa_id)
                reserved=int(await db.scalar(q))
                if b.jasa_id is None:
                    from app.models.retur_supplier import ReturSupplier,ReturSupplierItem
                    reserved+=int(await db.scalar(select(func.coalesce(func.sum(ReturSupplierItem.jumlah),0)).join(ReturSupplier).where(
                        ReturSupplier.status=='diajukan',ReturSupplierItem.tipe_pool=='finished_goods',ReturSupplierItem.satuan=='karung',
                        ReturSupplierItem.product_sku_id==b.sku_id,ReturSupplierItem.rice_quality_standard_id==b.std_id)))
                pools[key].update(karung_sebelum=stok['karung'],karung_bebas=stok['karung']-reserved,delta_karung=0)
        pools[key]['delta_kg']+=kg
        if b.tipe=='finished_goods':pools[key]['delta_karung']+=int(karung or 0)
        jenis=b.jenis if b.tipe=='byproduct_curah' else None
        if b.tipe=='finished_goods':
            sku=await db.get(ProductSku,b.sku_id)
            if sku and sku.kategori in {'broken','menir','reject','bekatul'}:jenis=sku.kategori
        if jenis:
            pool=('hasil_samping',b.jasa_id,jenis)
            if pool not in pools:
                curah=bk.BarisPerintah(tipe='byproduct_curah',jenis=jenis,jasa_id=b.jasa_id)
                free,label=await bk.tersedia(db,curah);physical,_=await bk.tersedia(db,curah,abaikan_pesanan=True)
                pools[pool]=dict(nama='Gabungan '+label,sumber=sumber(curah),stok_kg=physical,bebas_kg=free,delta_kg=0.)
            pools[pool]['delta_kg']+=kg
    for row,(old,new) in zip(rows,bars):
        await tambah(old,-float(row['sebelum']['berat_kg']),-int(row['sebelum']['jumlah_karung'] or 0))
        await tambah(new,float(row['sesudah']['berat_kg']),row['sesudah']['jumlah_karung'])
        row['nama_sebelum']=pools[bk._sumber_muatan(old)]['nama']
        row['nama_sesudah']=pools[bk._sumber_muatan(new)]['nama']
    for p in pools.values():
        if p['delta_kg']>max(0,p['bebas_kg'])+0.000001:
            raise ValueError(f"{p['nama']}: tambahan keluar melampaui saldo bebas; reservasi perintah lain tetap dilindungi.")
        p['stok_sesudah_kg']=p['stok_kg']-p['delta_kg']
        p['bebas_sesudah_kg']=p['bebas_kg']-p['delta_kg']
        if 'delta_karung' in p:
            if p['delta_karung']>max(0,p['karung_bebas']):raise ValueError(f"{p['nama']}: karung bebas tidak cukup untuk tambahan koreksi.")
            p['karung_sesudah']=p['karung_sebelum']-p['delta_karung']
    semua=list((await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id.in_(
        [r.id for r in anggota if r.status!='batal'])).order_by(OutgoingItem.id))).all())
    total=sum(float(i.berat_kg) for i in semua if i.outgoing_record_id!=rid)+sum(r['sesudah']['berat_kg'] for r in rows)
    tiket=None;berat_tiket=None
    if rec.timbangan_transaksi_id:
        berat_tiket,kode=await bk._tiket_keluar(db,rec.timbangan_transaksi_id)
        t=dict((await db.execute(text('SELECT * FROM timbangan_transaksi WHERE id=:id FOR UPDATE'),{'id':rec.timbangan_transaksi_id})).mappings().one())
        if not rec.kiriman_id and t.get('pelanggan_id') not in (None,pid):
            raise ValueError('Pelanggan pada tiket berbeda. Koreksi tiket melalui TeraFlow terlebih dahulu; PadiFlow tidak mengubah identitas tiket diam-diam.')
        other=select(OutgoingRecord.id).where(OutgoingRecord.timbangan_transaksi_id==rec.timbangan_transaksi_id,
            OutgoingRecord.status!='batal',OutgoingRecord.id.not_in([r.id for r in anggota]))
        if await db.scalar(other.limit(1)):raise ValueError('Tiket dipakai kiriman lain. Periksa hubungan perjalanan sebelum koreksi.')
        tiket={k:t.get(k) for k in ('id','kode','pelanggan_id','nomor_polisi','status_tiket','status_transaksi','timbang1_kg','timbang2_kg','berat_barang_kg','netto_timbangan_kg','total_tara_kg','jumlah_revisi','updated_at')}
        tiket['audit_terakhir']=await db.scalar(text("SELECT max(id) FROM timbangan_audit WHERE entitas='transaksi' AND entitas_id=:kode AND aksi='KOREKSI'"),{'kode':kode})
    periksa=bk.angka_verifikasi(total,berat_tiket)
    sebab=req.get('sebab_selisih','').strip()
    if periksa['sebab_wajib'] and not sebab:raise ValueError('Selisih total melewati ambang manual pengiriman. Isi sebab selisih pemeriksaan koreksi.')
    history=list((await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='outgoing_records',ActivityLog.record_id.in_([r.id for r in anggota])).order_by(ActivityLog.id))).all())
    snap=dict(versi=versi,pelaku=user.id,perintah_id=rid,kiriman_id=rec.kiriman_id,
        sebelum=dict(pelanggan_id=rec.pelanggan_id,nama=rec.nama_pembeli,jasa_id=rec.jasa_id),
        sesudah=dict(pelanggan_id=pid,nama=nama),barang=rows,sumber=list(pools.values()),tiket=tiket,
        pemeriksaan=periksa,alasan=req['alasan'].strip(),sebab_selisih=sebab,
        anggota=[dict(id=r.id,status=r.status,pelanggan_id=r.pelanggan_id,waktu_verifikasi=r.waktu_verifikasi,diverifikasi_oleh=r.diverifikasi_oleh) for r in anggota],
        muatan_armada=[item_snapshot(i) for i in semua],
        audit_awal=[dict(id=l.id,aksi=l.aksi,lalu=l.old_value,baru=l.new_value,alasan=l.alasan_perubahan,waktu=l.waktu_perubahan,oleh=l.changed_by) for l in history])
    snap=bersih(snap)
    return rec,items,snap


async def simpan(db,rid,user,req,*,dasar,kunci):
    izin(user)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}',kunci or ''):raise ValueError('Identitas permintaan tidak sah.')
    await bk._kunci_saldo_keluar(db)
    old=await db.get(KoreksiPengiriman,kunci)
    signature=sidik(req)
    if old:
        if old.outgoing_record_id!=rid or old.input_by!=user.id or old.sidik_input!=signature:
            raise ValueError('Identitas permintaan sudah dipakai untuk koreksi berbeda.')
        return old
    rec,items,snap=await rencana(db,rid,user,req)
    if not hmac.compare_digest(cap(snap),dasar or ''):raise ValueError('Data, saldo, retur, atau revisi tiket berubah. Isian tetap tersedia; baca dan periksa dampak terbaru sebelum konfirmasi ulang.')
    async with db.begin_nested():
        for i,row in zip(items,snap['barang']):
            baru=row['sesudah']
            for field in SUMBER:setattr(i,field,baru[field])
            i.berat_kg=D(str(baru['berat_kg']));i.jumlah_karung=baru['jumlah_karung']
        rec.pelanggan_id=snap['sesudah']['pelanggan_id'];rec.nama_pembeli=snap['sesudah']['nama']
        jasa_ids={r['sesudah']['jasa_id'] for r in snap['barang'] if float(r['sesudah']['berat_kg'])>0 and r['sesudah']['jasa_id']}
        rec.jasa_id=next(iter(jasa_ids)) if len(jasa_ids)==1 else None
        row=KoreksiPengiriman(kunci=kunci,outgoing_record_id=rid,versi=snap['versi']+1,
            sidik_input=signature,snapshot=snap,input_by=user.id,waktu=now_local())
        db.add(row)
        await log_activity(db,table_name='koreksi_pengiriman',record_id=rid,action='INSERT',
            changed_by=user.id,aksi='koreksi_pengiriman_selesai',old_value=json.dumps(snap['sebelum']),
            new_value=json.dumps(dict(kode=rec.kode,kunci=kunci,versi=row.versi,sesudah=snap['sesudah'],barang=snap['barang'])),
            alasan=snap['alasan'],pelanggan_ids={rec.pelanggan_id})
        await db.flush()
    return row
