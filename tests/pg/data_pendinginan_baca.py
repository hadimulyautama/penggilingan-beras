"""Satu lot per dryer sintetis; tidak menghubungi alat atau sumber luar."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.models import Dryer,DryingLot,DryingLotBatch,PurchaseBatch

WAKTU=datetime(2026,11,15,8,tzinfo=ZoneInfo('Asia/Jakarta'))

async def isi(pg,pabrik,jumlah):
    result=[]
    async with pg() as db:
        for i in range(jumlah):
            d=Dryer(nama=f'Dryer Uji {i:03}',warehouse_id=pabrik['g1'],kapasitas_kg=30000,status='aktif')
            db.add(d);await db.flush()
            lot=DryingLot(kode_lot=f'OPR-{i:03}',dryer_id=d.id,status='selesai',created_by=pabrik['user'],
                target_kadar_air=13,mode_dryer='15T',waktu_mulai_pengeringan=WAKTU-timedelta(hours=2),
                waktu_selesai_pengeringan=WAKTU-timedelta(minutes=40),waktu_mulai_pendinginan=WAKTU-timedelta(minutes=40),
                waktu_selesai_pendinginan=WAKTU-timedelta(minutes=10) if i%3==2 else None)
            db.add(lot);await db.flush()
            batch=PurchaseBatch(kode_batch=f'BOP-{i:03}',supplier_id=pabrik['pemasok'],berat_total_kg=8000+i,
                kondisi_gabah='basah',tanggal_pembelian=WAKTU.date(),waktu_pembelian=WAKTU,
                input_by=pabrik['user'],flag_unverified=False,sumber_berat='timbangan',status_batch='dikeringkan')
            db.add(batch);await db.flush();db.add(DryingLotBatch(drying_lot_id=lot.id,purchase_batch_id=batch.id))
            result.append(dict(id=lot.id,kode=lot.kode_lot,batch=batch.kode_batch,pendinginan=i%3!=2,dryer=d.id))
        await db.commit()
    return result
