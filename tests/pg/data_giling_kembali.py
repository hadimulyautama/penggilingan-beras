"""Riwayat sintetis terpisah; satu batch dan sumber per proses selesai."""
from datetime import timedelta
from sqlalchemy import select
from app.models import MillingProcess,MillingProcessSource,MillingProgressLog,PurchaseBatch,SiloStorage,Warehouse
from tests.pg.test_riwayat_giling import _giling_selesai

def salin(obj,**ubah):
    d={c.name:getattr(obj,c.name) for c in obj.__table__.columns if c.name!='id'}
    d.update(ubah);return type(obj)(**d)

async def isi(pg,pabrik,jumlah):
    async with pg() as db:
        if not await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2')):
            db.add(Warehouse(nama_gudang='Gudang 2 - Penyosohan',kode_fungsi='g2'));await db.commit()
    kode=await _giling_selesai(pg,pabrik)
    async with pg() as db:
        awal=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses==kode))
        sumber=await db.scalar(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==awal.id))
        batch=await db.get(PurchaseBatch,sumber.purchase_batch_id)
        silo=await db.get(SiloStorage,sumber.silo_storage_id)
        log=await db.scalar(select(MillingProgressLog).where(MillingProgressLog.milling_process_id==awal.id))
        for i in range(1,jumlah):
            b=salin(batch,kode_batch=f'GB-UJG-{i:05}');db.add(b);await db.flush()
            s=salin(silo,purchase_batch_id=b.id,milling_process_id=None);db.add(s);await db.flush()
            p=salin(awal,kode_proses=f'LOT-UJG-{i:05}',purchase_batch_id=b.id,silo_storage_id=s.id,waktu_mulai=awal.waktu_mulai+timedelta(minutes=i),waktu_selesai=awal.waktu_selesai+timedelta(minutes=i))
            db.add(p);await db.flush();s.milling_process_id=p.id
            db.add(salin(sumber,milling_process_id=p.id,silo_storage_id=s.id,purchase_batch_id=b.id))
            db.add(salin(log,milling_process_id=p.id))
        await db.commit()
