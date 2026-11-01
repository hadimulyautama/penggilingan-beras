"""Catatan timbang hasil drying; tidak mengganti penerimaan atau mutasi stok.

Memakai metadata proses terpadu dan activity_logs yang sudah ada. Pencatatan
pasti hanya dari hasil flowing scale, bukan konversi estimasi menjadi aktual.
Transaksi dimiliki endpoint; semua koreksi mempertahankan audit sebelum/sesudah.
"""
import hashlib
import hmac
import json
from decimal import Decimal
from sqlalchemy import select
from app.database import now_local
from app.models import DryingLot, DryingLotBatch, PurchaseBatch, SiloStorage
from hmu_core.proses_db import ProsesTerpadu
from app.services.estimasi_pengeringan import angka, untuk_lot_banyak
from app.services.activity_log import log_activity


def sidik(value):
    return hashlib.sha256(json.dumps(value,default=str,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def cap(value):
    from app.web.security import _kunci
    key=_kunci()
    return hmac.new(key.encode() if isinstance(key,str) else key,sidik(value).encode(),hashlib.sha256).hexdigest()


async def konteks(db, *, lot_id, user, kunci=False):
    from app.web.api import _is_g1_operator
    if not await _is_g1_operator(user):
        raise PermissionError('Pencatatan bobot pengeringan mengikuti izin Gudang 1 pada peran efektif.')
    q=select(DryingLot).where(DryingLot.id==lot_id)
    lot=await db.scalar(q.with_for_update() if kunci else q)
    if not lot or lot.status!='selesai' or not lot.waktu_selesai_pengeringan:
        raise ValueError('Lot belum selesai dikeringkan atau tidak tersedia.')
    q=select(SiloStorage).where(SiloStorage.drying_lot_id==lot.id).order_by(SiloStorage.id)
    placements=(await db.scalars(q.with_for_update() if kunci else q)).all()
    if not lot.waktu_selesai_pendinginan or not placements:
        raise ValueError('Bobot flowing scale baru dapat dicatat setelah pemindahan ke silo selesai.')
    if any(row.jasa_id!=lot.jasa_id for row in placements):
        raise ValueError('Pemilik pada catatan pemindahan harus diperiksa terlebih dahulu.')
    q=select(PurchaseBatch).join(DryingLotBatch,DryingLotBatch.purchase_batch_id==PurchaseBatch.id).where(DryingLotBatch.drying_lot_id==lot.id).order_by(PurchaseBatch.id)
    batches=(await db.scalars(q.with_for_update() if kunci else q)).all()
    if not batches or any(b.jasa_id!=lot.jasa_id for b in batches):
        raise ValueError('Hubungan bahan dan pemilik lot harus diperiksa terlebih dahulu.')
    q=select(ProsesTerpadu).where(ProsesTerpadu.aplikasi=='produksi',ProsesTerpadu.tabel_sumber=='drying_lots',ProsesTerpadu.id_sumber==str(lot.id))
    proses=await db.scalar(q.with_for_update() if kunci else q)
    metadata=dict(proses.metadata_domain or {}) if proses else {}
    old=metadata.get('bobot_kering_terukur')
    if old is not None and not isinstance(old,dict):
        raise ValueError('Catatan timbang tersimpan tidak lengkap; periksa audit sebelum membuat koreksi.')
    dasar=dict(actor=user.id,lot=(lot.id,lot.jasa_id,lot.status,lot.waktu_selesai_pengeringan),
        sumber=[(b.id,b.jasa_id,b.berat_total_kg,b.sumber_berat,b.retur_supplier_keluar_kg) for b in batches],
        penempatan=[(r.id,r.silo_id,r.jasa_id,r.tanggal_masuk) for r in placements],
        refs=proses.referensi_asal if proses else None,terukur=old)
    tampil=dict(lot_id=lot.id,kode=lot.kode_lot,bobot=(await untuk_lot_banyak(db,[lot]))[lot.id],
        terukur=old,dasar=cap(dasar),penempatan_ids=[r.id for r in placements])
    return tampil,lot,proses,batches


async def simpan(db, *, lot_id,user,kg,referensi,alasan,konfirmasi,dasar,kunci):
    n=angka(kg)
    if n is None or n<=0 or n>Decimal('9999999999.99') or n!=n.quantize(Decimal('.01')):
        raise ValueError('Bobot wajib positif dan paling banyak dua angka desimal dalam kg.')
    referensi=(referensi or '').strip();alasan=(alasan or '').strip()
    if not referensi or not konfirmasi:
        raise ValueError('Referensi hasil flowing scale dan konfirmasi penimbangan wajib diisi.')
    if not kunci or len(kunci)>100:raise ValueError('Identitas permintaan tidak sah.')
    signature=sidik(dict(kg=format(n,'.2f'),referensi=referensi,alasan=alasan))
    data,lot,proses,batches=await konteks(db,lot_id=lot_id,user=user,kunci=True)
    old=data['terukur']
    if old and old.get('kunci')==kunci:
        if old.get('signature')!=signature or old.get('pencatat')!=user.id:
            raise ValueError('Identitas permintaan sudah dipakai untuk isian berbeda.')
        return data
    if old and old.get('signature')==signature:
        return data  # Same measurement/reference, even if a retry generated a new key.
    if not hmac.compare_digest(data['dasar'],dasar or ''):
        raise ValueError('Data atau catatan timbang berubah. Isian tetap tersedia; periksa data terbaru sebelum konfirmasi ulang.')
    if old and not alasan:raise ValueError('Alasan koreksi bobot terukur wajib diisi.')
    if proses is None:
        # Pengukuran baru pada lot historis; tidak menciptakan arus stok baru.
        proses=ProsesTerpadu(aplikasi='produksi',tabel_sumber='drying_lots',id_sumber=str(lot.id),kode=lot.kode_lot,
            jenis='pengeringan',status='selesai',jenis_pemilik='jasa' if lot.jasa_id else 'pabrik',
            id_pemilik=lot.jasa_id,waktu_mulai=lot.waktu_mulai_pengeringan,waktu_selesai=lot.waktu_selesai_pengeringan,
            referensi_asal=[b.kode_batch for b in batches],metadata_domain={})
        db.add(proses)
    new=dict(kg=format(n,'.2f'),metode='flowing_scale',referensi=referensi,alasan=alasan,
        waktu=now_local().isoformat(),pencatat=user.id,pencatat_nama=user.nama,
        penempatan_ids=data['penempatan_ids'],kunci=kunci,signature=signature,
        versi=int((old or {}).get('versi',0))+1)
    proses.metadata_domain={**(proses.metadata_domain or {}),'bobot_kering_terukur':new}
    await log_activity(db,table_name='drying_lots',record_id=lot.id,action='UPDATE',changed_by=user.id,
        field_name='bobot_kering_terukur',old_value=json.dumps(old) if old else None,
        new_value=json.dumps(new),alasan=alasan or 'Pencatatan hasil flowing scale',aksi='catat_bobot_kering_terukur')
    await db.flush()
    return (await konteks(db,lot_id=lot_id,user=user))[0]
