"""Arsip sintetis dari satu pengajuan sah dan salinan pembatalan historis."""
from datetime import timedelta
from sqlalchemy import select,insert
from app.models.retur_supplier import ReturSupplier as R,ReturSupplierItem as I
from tests.pg.test_retur_supplier import buat


async def arsip(db,asal,n=45):
    seed=await buat(db,asal);await db.commit()
    item=await db.scalar(select(I).where(I.retur_supplier_id==seed.id))
    raw={c.name:getattr(seed,c.name) for c in R.__table__.columns if c.name not in ('id','created_at','updated_at')}
    values=[dict(raw,kode=f'RET-ARSIP-{i:05}',kunci=f'arsip-{i:05}',status='dibatalkan',alasan_batal='Arsip pembatalan sintetis',dibatalkan_oleh=asal['uid'],dibatalkan_pada=seed.waktu,waktu=seed.waktu-timedelta(minutes=i//3)) for i in range(1,n)]
    ids=(await db.scalars(insert(R).returning(R.id),values)).all()
    rawitem={c.name:getattr(item,c.name) for c in I.__table__.columns if c.name not in ('id','retur_supplier_id')}
    await db.execute(insert(I),[dict(rawitem,retur_supplier_id=rid) for rid in ids]);await db.commit()
    return [seed.id,*ids]
