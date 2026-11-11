"""Pisahkan bobot sumber giling menurut kondisi penerimaan, tanpa perkiraan."""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select
from app import models as m


async def per_kondisi(db,proses):
    sources=(await db.scalars(select(m.MillingProcessSource).where(
        m.MillingProcessSource.milling_process_id.in_(proses)))).all()
    per_proses=defaultdict(list)
    for s in sources:per_proses[s.milling_process_id].append((s.drying_lot_id,s.purchase_batch_id,s.berat_kg))
    for p in proses.values():
        if not per_proses[p.id]:per_proses[p.id]=[(p.drying_lot_id,p.purchase_batch_id,p.berat_gabah_masuk_kg)]
    lot_ids={lot for ss in per_proses.values() for lot,_,_ in ss if lot}
    batch_ids={bid for ss in per_proses.values() for _,bid,_ in ss if bid}
    lot_batch=defaultdict(list)
    for lid,bid in (await db.execute(select(m.DryingLotBatch.drying_lot_id,m.DryingLotBatch.purchase_batch_id)
        .where(m.DryingLotBatch.drying_lot_id.in_(lot_ids or {0})))).all():
        lot_batch[lid].append(bid);batch_ids.add(bid)
    kondisi=dict((await db.execute(select(m.PurchaseBatch.id,m.PurchaseBatch.kondisi_gabah)
        .where(m.PurchaseBatch.id.in_(batch_ids or {0})))).all())
    hasil={}
    for pid,ss in per_proses.items():
        p=proses[pid];totals={'basah':Decimal(0),'kering':Decimal(0)}
        total=Decimal(0);lengkap=bool(p.bobot_masuk_final and p.berat_gabah_masuk_kg is not None)
        for lid,bid,weight in ss:
            ids=lot_batch[lid] if lid else [bid]
            kinds={(kondisi.get(b) or '').strip().lower() for b in ids}
            if len(kinds)!=1 or not kinds<={'basah','kering'} or weight is None:
                lengkap=False;continue
            w=Decimal(str(weight));totals[next(iter(kinds))]+=w;total+=w
        # Dasar harus sama dengan total bahan/rendemen yang sudah dipakai
        # laporan. Selisih sumber tidak dibagi rata atau ditebak proporsional.
        if p.berat_gabah_masuk_kg is None or abs(total-Decimal(str(p.berat_gabah_masuk_kg)))>Decimal('.001'):
            lengkap=False
        hasil[pid]=totals if lengkap else {'basah':None,'kering':None}
    return hasil
