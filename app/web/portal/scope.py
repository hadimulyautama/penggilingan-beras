"""Trusted read capability: identity comes exclusively from the customer session."""
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import select, text
from app.database import SessionLocal
from app.models import (Jasa, PurchaseBatch, PkPurchaseBatch, DryingLot,
                        MillingProcess, PolishingProcess, InternalTransfer)
from .security import CustomerReader

MODELS = {
    'pengeringan': (DryingLot, 'kode_lot'), 'pendinginan': (DryingLot, 'kode_lot'),
    'giling': (MillingProcess, 'kode_proses'), 'sosoh': (PolishingProcess, 'kode_proses'),
    'transfer': (InternalTransfer, 'kode_transfer'),
    'gabah-basah': (PurchaseBatch, 'kode_batch'), 'gabah-kering': (PurchaseBatch, 'kode_batch'),
    'pk-luar': (PkPurchaseBatch, 'kode_batch'), 'pk-hasil-giling': (MillingProcess, 'kode_proses'),
}


@dataclass(frozen=True)
class ReadScope:
    reader: CustomerReader
    jasa_ids: frozenset[int]
    codes: frozenset[str]
    resources: dict[str, frozenset[int]]

    def ids(self, model):
        return self.resources.get(model.__tablename__, frozenset())


def missing():
    raise HTTPException(404, 'Catatan tidak ditemukan.')


async def load_scope(reader):
    from app.models import (OutgoingRecord, OutgoingItem, CustomerReturn, CustomerReturnItem,
                            PkGudang2Intake, DryingLotBatch, MillingProcessSource)
    from app.penggilingan.inventory.models import ReturRincian
    async with SessionLocal() as db:
        ids = frozenset((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id == reader.pelanggan_id))).all())
        objects = {}
        models = set(m for m, _ in MODELS.values()) | {PkGudang2Intake}
        for model in models:
            objects[model] = {r.id:r for r in (await db.scalars(select(model).where(model.jasa_id.in_(ids)))).all()}
        # Fail closed on inconsistent imports / mixed physical lots. An owner
        # label alone must not authorize somebody else's source batch.
        drying = objects[DryingLot]
        sources = (await db.execute(select(DryingLotBatch.drying_lot_id, PurchaseBatch.jasa_id)
            .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
            .where(DryingLotBatch.drying_lot_id.in_(drying)))).all()
        for lid, jid in sources:
            if jid not in ids:drying.pop(lid, None)
        mills = objects[MillingProcess]
        for mid,proc in list(mills.items()):
            if ((proc.purchase_batch_id and proc.purchase_batch_id not in objects[PurchaseBatch]) or
                (proc.drying_lot_id and proc.drying_lot_id not in drying)):
                mills.pop(mid,None)
        for source in (await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id.in_(mills)))).all():
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
            select(OutgoingItem.outgoing_record_id).where(OutgoingItem.jasa_id.in_(ids)))))).all()
        outitems = (await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id.in_([x.id for x in outs])))).all()
        grouped = {}
        for item in outitems:grouped.setdefault(item.outgoing_record_id,[]).append(item.jasa_id)
        outids = frozenset(o.id for o in outs if grouped.get(o.id) and all(j in ids for j in grouped[o.id]))
        resources[OutgoingRecord.__tablename__] = outids
        rets = (await db.scalars(select(CustomerReturn).where(CustomerReturn.id.in_(
            select(CustomerReturnItem.customer_return_id).where(CustomerReturnItem.jasa_id.in_(ids)))))).all()
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


async def _unsafe_polishing_sources(db, processes, ids, safe_intakes):
    """Batch ownership validation across actual silo occupation windows.

    The number of DB queries stays constant as customer history grows. Silo
    reuse is delimited by the previous completed emptying, preserving the
    same source boundaries used by production history/PDF composers.
    """
    from bisect import bisect_left
    from collections import defaultdict
    from app.models import (PolishingSiloUsage, PkGudang2Intake, PkTumpukanToSilo,
                            BrokenKeSilo, BerasKeSilo, HasilSampingKeSilo)
    usages=(await db.scalars(select(PolishingSiloUsage).where(
        PolishingSiloUsage.polishing_process_id.in_(processes)))).all()
    silos={u.silo_id for u in usages}
    if not silos:return set()
    resets=defaultdict(list)
    for sid,finished in (await db.execute(select(PolishingSiloUsage.silo_id,PolishingProcess.waktu_selesai)
        .join(PolishingProcess,PolishingProcess.id==PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id.in_(silos),PolishingSiloUsage.berat_akhir_kg==0,
               PolishingProcess.waktu_selesai.is_not(None)))).all():
        resets[sid].append(finished)
    for values in resets.values():values.sort()
    movements=defaultdict(list)
    for model,datecol in [(PkGudang2Intake,'waktu_masuk'),(BrokenKeSilo,'waktu'),(BerasKeSilo,'waktu'),(HasilSampingKeSilo,'waktu')]:
        for row in (await db.scalars(select(model).where(model.silo_id.in_(silos)))).all():
            owner=row.jasa_id
            if model is PkGudang2Intake and row.id not in safe_intakes:owner=None
            movements[row.silo_id].append((getattr(row,datecol),owner))
    for move,intake in (await db.execute(select(PkTumpukanToSilo,PkGudang2Intake)
        .join(PkGudang2Intake,PkGudang2Intake.id==PkTumpukanToSilo.pk_gudang2_intake_id)
        .where(PkTumpukanToSilo.silo_id.in_(silos)))).all():
        movements[move.silo_id].append((move.waktu,intake.jasa_id if intake.id in safe_intakes else None))
    unsafe=set()
    for usage in usages:
        proc=processes[usage.polishing_process_id]
        times=resets[usage.silo_id]
        pos=bisect_left(times,proc.waktu_mulai)
        previous=times[pos-1] if pos else None
        for stamp,owner in movements[usage.silo_id]:
            if previous and stamp<=previous:continue
            if proc.waktu_selesai and stamp>proc.waktu_selesai:continue
            if owner not in ids:
                unsafe.add(proc.id);break
    return unsafe


def is_customer_read(request):
    return request.method=='GET' and isinstance(getattr(request.state,'portal_scope',None),ReadScope)


async def own_model(scope, kind, identity, *, by_code=False):
    if kind not in MODELS:missing()
    model,column = MODELS[kind]
    async with SessionLocal() as db:
        row = await db.scalar(select(model).where(model.id.in_(scope.ids(model)),
            (getattr(model,column)==identity) if by_code else (model.id==identity)))
    if row is None:missing()
    return row


async def own_ticket(scope, tid, *, retur=False):
    if tid not in scope.resources['timbangan_transaksi']:missing()
    async with SessionLocal() as db:
        row = (await db.execute(text('SELECT id,kode FROM timbangan_transaksi WHERE id=:id AND arah=:arah'),
            {'id':tid,'arah':'RETUR_MASUK' if retur else 'MASUK'})).first()
    if not row:missing()
    return row


async def own_order(scope,jid):
    if jid not in scope.jasa_ids:missing()


async def own_outgoing(scope,oid):
    from app.models import OutgoingRecord
    if oid not in scope.ids(OutgoingRecord):missing()
