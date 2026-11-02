"""Pembaca acuan sebelum optimasi SQL, hanya untuk uji kesetaraan."""
from app.web.portal.scope import ReadScope,MODELS
from app.models import Jasa,PurchaseBatch,PkPurchaseBatch,DryingLot,MillingProcess,PolishingProcess,InternalTransfer
from app.performa import dalam
from app.web.portal.scope import _unsafe_polishing_sources
from types import SimpleNamespace
from sqlalchemy import select,text
from app.web.portal import scope as _live
async def load_scope_acuan(reader):
    from app.models import (OutgoingRecord, OutgoingItem, CustomerReturn, CustomerReturnItem,
                            PkGudang2Intake, DryingLotBatch, MillingProcessSource)
    from app.penggilingan.inventory.models import ReturRincian
    async with _live.SessionLocal() as db:
        ids = frozenset((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id == reader.pelanggan_id))).all())
        objects = {}
        models = set(m for m, _ in MODELS.values()) | {PkGudang2Intake}
        for model in models:
            # Capability hanya membutuhkan identitas dan relasi sumber;
            # catatan/angka detail dibaca di halaman detail yang diminta.
            names = {'id','jasa_id'} | {col for m,col in MODELS.values() if m is model}
            names.update({MillingProcess: ('purchase_batch_id','drying_lot_id'),
                InternalTransfer: ('milling_process_id',),
                PkGudang2Intake: ('internal_transfer_id','pk_purchase_batch_id'),
                PolishingProcess: ('waktu_mulai','waktu_selesai')}.get(model,()))
            rows=(await db.execute(select(*(getattr(model,n) for n in sorted(names)))
                .where(dalam(db, model.jasa_id, ids)))).mappings().all()
            objects[model] = {r['id']:SimpleNamespace(**r) for r in rows}
        # Fail closed on inconsistent imports / mixed physical lots. An owner
        # label alone must not authorize somebody else's source batch.
        drying = objects[DryingLot]
        sources = (await db.execute(select(DryingLotBatch.drying_lot_id, PurchaseBatch.jasa_id)
            .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
            .where(dalam(db, DryingLotBatch.drying_lot_id, drying)))).all()
        for lid, jid in sources:
            if jid not in ids:drying.pop(lid, None)
        mills = objects[MillingProcess]
        for mid,proc in list(mills.items()):
            if ((proc.purchase_batch_id and proc.purchase_batch_id not in objects[PurchaseBatch]) or
                (proc.drying_lot_id and proc.drying_lot_id not in drying)):
                mills.pop(mid,None)
        for source in (await db.execute(select(MillingProcessSource.milling_process_id,
                MillingProcessSource.purchase_batch_id,MillingProcessSource.drying_lot_id)
                .where(dalam(db, MillingProcessSource.milling_process_id, mills)))).all():
            if ((source.purchase_batch_id and source.purchase_batch_id not in objects[PurchaseBatch]) or
                (source.drying_lot_id and source.drying_lot_id not in drying)):
                mills.pop(source.milling_process_id, None)
        transfers = objects[InternalTransfer]
        transfers = {i:r for i,r in transfers.items() if r.milling_process_id in mills}
        objects[InternalTransfer] = transfers
        intakes = objects[PkGudang2Intake]
        objects[PkGudang2Intake] = {i:r for i,r in intakes.items() if
            (not r.internal_transfer_id or r.internal_transfer_id in transfers) and
            (not r.pk_purchase_batch_id or r.pk_purchase_batch_id in objects[PkPurchaseBatch])}
        unsafe_polishing=await _unsafe_polishing_sources(db,objects[PolishingProcess],ids,frozenset(objects[PkGudang2Intake]))
        for pid in unsafe_polishing:objects[PolishingProcess].pop(pid,None)
        resources = {m.__tablename__:frozenset(rows) for m,rows in objects.items()}
        codes = {getattr(r,col) for m,col in set(MODELS.values()) for r in objects[m].values()}
        outs = (await db.scalars(select(OutgoingRecord).where(OutgoingRecord.id.in_(
            select(OutgoingItem.outgoing_record_id).where(dalam(db, OutgoingItem.jasa_id, ids)))))).all()
        outitems = (await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id.in_([x.id for x in outs])))).all()
        grouped = {}
        for item in outitems:grouped.setdefault(item.outgoing_record_id,[]).append(item.jasa_id)
        outids = frozenset(o.id for o in outs if grouped.get(o.id) and all(j in ids for j in grouped[o.id]))
        resources[OutgoingRecord.__tablename__] = outids
        rets = (await db.scalars(select(CustomerReturn).where(CustomerReturn.id.in_(
            select(CustomerReturnItem.customer_return_id).where(dalam(db, CustomerReturnItem.jasa_id, ids)))))).all()
        retitems = (await db.scalars(select(CustomerReturnItem).where(CustomerReturnItem.customer_return_id.in_([x.id for x in rets])))).all()
        grouped = {}
        for item in retitems:grouped.setdefault(item.customer_return_id,[]).append(item.jasa_id)
        resources[CustomerReturn.__tablename__] = frozenset(r.id for r in rets if grouped.get(r.id) and all(j in ids for j in grouped[r.id]))
        resources[ReturRincian.__tablename__] = frozenset((await db.scalars(select(ReturRincian.id).where(ReturRincian.outgoing_record_id.in_(outids)))).all())
        related_tickets=set((await db.scalars(select(CustomerReturn.timbangan_transaksi_id).where(CustomerReturn.id.in_(resources[CustomerReturn.__tablename__])))).all())
        related_tickets.update((await db.scalars(select(ReturRincian.timbangan_transaksi_id).where(ReturRincian.id.in_(resources[ReturRincian.__tablename__])))).all())
        resources['timbangan_transaksi'] = frozenset(related_tickets-{None}) | frozenset((await db.scalars(text(
            "SELECT id FROM timbangan_transaksi WHERE pelanggan_id=:pid AND jasa=TRUE AND arah IN ('MASUK','RETUR_MASUK')"), {'pid':reader.pelanggan_id})).all())
    return ReadScope(reader,ids,frozenset(codes),resources)
