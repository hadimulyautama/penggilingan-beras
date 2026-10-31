"""Proyeksi baca perjalanan dan saldo retur. Tidak memeriksa/menerima retur.

Identitas item tetap milik perintah pelanggan; total tiket hanya di kepala.
Portal dibatasi sebelum anggota kiriman dibaca, bukan disembunyikan lewat CSS.
"""
from decimal import Decimal
from sqlalchemy import select,text
from fastapi import HTTPException
from app.models import OutgoingRecord,OutgoingItem,ActivityLog,CustomerReturn,Pelanggan,Warehouse,User,RiceQualityStandard,KoreksiPengiriman
from app.penggilingan.inventory.models import ReturRincian
from app.services import barang_keluar as bk,retur_pengajuan as retur
from app.services.jasa import nama_pemilik_banyak
from app.web.layar_keluar import _nama_barang,_nama_orang


async def baca(db,rec,*,scope=None,boleh_retur=False):
    if scope and rec.id not in scope.ids(OutgoingRecord):
        raise HTTPException(404,'Pengiriman tidak ditemukan.')
    # Jangan membaca anggota lain, total armada, ataupun tiket gabungan portal.
    anggota=[rec] if scope else await bk.anggota_kiriman(db,rec)
    ids=[r.id for r in anggota]
    koreksi=list((await db.scalars(select(KoreksiPengiriman).where(KoreksiPengiriman.outgoing_record_id.in_(ids)).order_by(KoreksiPengiriman.versi.desc()))).all()) if boleh_retur and not scope else []
    items=list((await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id.in_(ids)).order_by(OutgoingItem.id))).all())
    if scope and (not items or any(i.jasa_id not in scope.jasa_ids for i in items)):
        raise HTTPException(404,'Pengiriman tidak ditemukan.')
    rows=[(r,[i for i in items if i.outgoing_record_id==r.id]) for r in anggota]
    nama=await _nama_barang(db,rows);orang=await _nama_orang(db,rows)
    orang.update(dict((await db.execute(select(User.id,User.nama).where(User.id.in_([r.input_by for r in anggota])))).all()))
    mutu=dict((await db.execute(select(RiceQualityStandard.id,RiceQualityStandard.kode).where(RiceQualityStandard.id.in_([i.rice_quality_standard_id for i in items if i.rice_quality_standard_id])))).all())
    pemilik=await nama_pemilik_banyak(db,{i.jasa_id for i in items if i.jasa_id})
    pelanggan=dict((await db.execute(select(Pelanggan.id,Pelanggan.nama_pelanggan).where(Pelanggan.id.in_([r.pelanggan_id for r in anggota if r.pelanggan_id])))).all())
    gudang=dict((await db.execute(select(Warehouse.kode_fungsi,Warehouse.nama_gudang))).all())
    logs=list((await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='outgoing_records',ActivityLog.record_id.in_(ids),ActivityLog.dibatalkan_pada.is_(None)).order_by(ActivityLog.id.desc()))).all())
    def terakhir(rid,aksi):return next((l for l in logs if l.record_id==rid and l.aksi==aksi),None)
    applications=list((await db.scalars(select(ReturRincian).where(ReturRincian.outgoing_record_id.in_(ids)).order_by(ReturRincian.id.desc()))).all()) if boleh_retur or scope else []
    receipts={r.id:r for r in (await db.scalars(select(CustomerReturn).where(CustomerReturn.id.in_([a.customer_return_id for a in applications if a.customer_return_id])))).all()}
    pelanggan_data=[]
    for r,baris in rows:
        # Sisa dari layanan yang dipakai penulis; tidak membuat saldo tandingan.
        _,pakai=await retur.sisa_asal(db,r.id) if boleh_retur or scope else ([],{})
        barang=[]
        for i in baris:
            p=Decimal(str(i.berat_perintah_kg)) if i.berat_perintah_kg is not None else None
            a=Decimal(str(i.berat_kg));bag=i.item_type=='finished_goods'
            usage=pakai.get(i.id)
            sent=Decimal(i.jumlah_karung or 0) if bag else a
            key='karung' if bag else 'kg'
            balance=None if usage is None else dict(diterima=usage['diterima_'+key],tertunda=usage[key]-usage['diterima_'+key],sisa=max(sent-usage[key],0),satuan='karung' if bag else 'kg')
            barang.append(dict(id=i.id,nama=nama.get(i.id,'Barang historis'),mutu=mutu.get(i.rice_quality_standard_id),pemilik=pemilik.get(i.jasa_id,'Milik pabrik'),gudang=gudang.get(bk.GUDANG_ITEM.get(i.item_type),'Gudang belum tercatat'),perintah=p,aktual=a,tidak_terkirim=max(p-a,0) if p is not None else None,karung_perintah=i.jumlah_karung_perintah,karung_aktual=i.jumlah_karung,saldo=balance))
        close=terakhir(r.id,'barang_keluar_muat');verify=terakhir(r.id,'barang_keluar_verifikasi')
        metode=('otomatis' if verify and ' · otomatis ±0,2% setelah tara' in (verify.new_value or '') else 'manual' if verify else 'tidak tercatat')
        related=[dict(rincian=a,penerimaan=receipts.get(a.customer_return_id),berat=sum((Decimal(m['berat_kg']) for m in a.muatan),Decimal(0))) for a in applications if a.outgoing_record_id==r.id]
        pelanggan_data.append(dict(rec=r,koreksi=[k for k in koreksi if k.outgoing_record_id==r.id],nama=r.nama_pembeli or pelanggan.get(r.pelanggan_id,'Pelanggan belum tercatat'),barang=barang,aktual=sum((b['aktual'] for b in barang),Decimal(0)),perintah=sum((b['perintah'] for b in barang),Decimal(0)) if all(b['perintah'] is not None for b in barang) else None,tidak_terkirim=sum((b['tidak_terkirim'] for b in barang),Decimal(0)) if all(b['tidak_terkirim'] is not None for b in barang) else None,alasan=close.alasan_perubahan if close else None,metode=metode,retur=related,
            jejak=[dict(label=label,waktu=t,nama=orang.get(uid,'Petugas belum tercatat')) for label,t,uid in [('Diperintahkan' if r.waktu_perintah else 'Pencatatan',r.waktu_perintah or r.waktu,r.diperintah_oleh if r.waktu_perintah else r.input_by),('Selesai muat',r.waktu_muat,r.dimuat_oleh),('Diverifikasi '+metode,r.waktu_verifikasi,r.diverifikasi_oleh)] if t]))
    aktif=[p for p in pelanggan_data if p['rec'].status!='batal']
    total=sum((p['aktual'] for p in aktif),Decimal(0))
    tiket=None
    if rec.timbangan_transaksi_id and not (scope and rec.kiriman_id):
        tiket=(await db.execute(text('''SELECT id,kode,status_tiket,status_transaksi,nama_sopir,nomor_polisi,timbang1_kg,timbang2_kg,timbang1_waktu,timbang2_waktu,berat_kosong_kg,berat_bermuatan_kg,netto_timbangan_kg,total_tara_kg,tara_lain_kg,berat_barang_kg FROM timbangan_transaksi WHERE id=:id'''),{'id':rec.timbangan_transaksi_id})).mappings().first()
        if tiket:
            tiket=dict(tiket);tiket['legacy']=tiket['berat_barang_kg'] in (None,0)
            # SQL_REAL_TIKET lama memakai netto sebagai kaki kompatibilitas.
            from app.penggilingan.gudang1.services.timbang_link import SQL_REAL_TIKET
            tiket['pembanding']=await db.scalar(text(f'SELECT {SQL_REAL_TIKET} FROM timbangan_transaksi t WHERE id=:id'),{'id':rec.timbangan_transaksi_id})
            tiket['selisih']=None if tiket['pembanding'] is None else Decimal(str(tiket['pembanding']))-total
    return dict(rec=rec,plat=rec.kiriman.no_polisi if rec.kiriman else rec.no_polisi,ekspedisi=rec.kiriman.nama_ekspedisi if rec.kiriman else rec.nama_ekspedisi,pelanggan=pelanggan_data,total=total,perintah=sum((p['perintah'] for p in aktif),Decimal(0)) if all(p['perintah'] is not None for p in aktif) else None,tidak_terkirim=sum((p['tidak_terkirim'] for p in aktif),Decimal(0)) if all(p['tidak_terkirim'] is not None for p in aktif) else None,jumlah_item=sum(len(p['barang']) for p in pelanggan_data),jumlah_pelanggan=len(pelanggan_data),tiket=tiket,portal=bool(scope),tiket_dibatasi=bool(scope and rec.kiriman_id),boleh_retur=boleh_retur and not scope,status='Dibatalkan' if not aktif else 'Selesai' if all(p['rec'].status=='selesai' for p in aktif) else 'Masih berjalan')
