"""Trusted read capability: identity comes exclusively from the customer session."""
from app.performa import dalam
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
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

    def __post_init__(self):
        # Scope baca tidak boleh berubah setelah lolos pemeriksaan sumber.
        object.__setattr__(self,'resources',MappingProxyType({k:frozenset(v) for k,v in self.resources.items()}))

    def __deepcopy__(self,memo):
        # Reader frozen, resource frozenset di balik mapping read-only.
        # Capability tidak membawa sesi/ORM atau objek yang dapat diubah.
        return self

    @cached_property
    def kunci_performa(self):
        # Semua batas pemilik/sumber tetap masuk kunci, dihitung sekali
        # selama request, bukan menyalin ribuan ID untuk setiap memo kecil.
        return (type(self),self.reader,self.jasa_ids,self.codes,frozenset(self.resources.items()))

    def ids(self, model):
        return self.resources.get(model.__tablename__, frozenset())


def missing():
    raise HTTPException(404, 'Catatan tidak ditemukan.')


from app.performa import NilaiSingkat
_scope_bersama=NilaiSingkat(detik=2,batas=16)


async def load_scope(reader):
    """Gabungkan pembacaan hanya selama WAL dan snapshot transaksi primary belum berubah.

    Setiap request membaca posisi WAL dan transaksi yang masih aktif.
    Snapshot transaksi juga membedakan commit yang WAL-nya sudah ditulis
    tetapi datanya belum terlihat. Izin tidak dibagi melintasi commit.
    Perubahan lain pada cluster hanya menambah cache miss, bukan akses.
    Tidak dipakai pada standby/SQLite, dan akun/sesi tetap diperiksa terpisah.
    """
    async with SessionLocal() as db:
        primary=db.get_bind().dialect.name=='postgresql'
        posisi=await db.scalar(text("SELECT CASE WHEN pg_is_in_recovery() THEN NULL ELSE pg_current_wal_insert_lsn()::text || ':' || txid_current_snapshot()::text END")) if primary else None
        bind=db.get_bind()
    # Lepas koneksi probe sebelum menunggu pembaca bersama, agar waiter
    # tidak memenuhi pool sementara pembaca menunggu koneksi sendiri.
    if posisi is None:return await _load_scope_sql(reader)
    return await _scope_bersama.ambil((bind,reader,posisi),lambda:_load_scope_sql(reader))


async def _load_scope_sql(reader):
    """Validasi sumber di SQL tanpa membangun seluruh objek riwayat di Python.

    Capability tetap dibaca ulang pada setiap request. CTE membatasi pemilik
    dan sumber sebelum ID diteruskan ke pembaca halaman; tidak ada cache izin.
    """
    from collections import defaultdict
    from sqlalchemy import union_all, literal, null, table, column, or_
    from app.models import (OutgoingRecord, OutgoingItem, CustomerReturn, CustomerReturnItem,
                            PkGudang2Intake, DryingLotBatch, MillingProcessSource)
    from app.penggilingan.inventory.models import ReturRincian
    own = select(Jasa.id).where(Jasa.pelanggan_id == reader.pelanggan_id).cte('scope_jasa')
    own_ids = select(own.c.id)
    batch = select(PurchaseBatch.id).where(PurchaseBatch.jasa_id.in_(own_ids)).cte('scope_batch')
    pk = select(PkPurchaseBatch.id).where(PkPurchaseBatch.jasa_id.in_(own_ids)).cte('scope_pk')
    # Sama dengan pembaca acuan: sumber drying diperiksa lewat batch yang
    # terlihat (cermin batal otomatis disaring oleh event ORM).
    dry_bad = select(DryingLotBatch.id).join(PurchaseBatch,
        PurchaseBatch.id == DryingLotBatch.purchase_batch_id).where(
            DryingLotBatch.drying_lot_id == DryingLot.id,
            or_(PurchaseBatch.jasa_id.is_(None), ~PurchaseBatch.jasa_id.in_(own_ids))).exists()
    dry = select(DryingLot.id).where(DryingLot.jasa_id.in_(own_ids), ~dry_bad).cte('scope_dry')
    batch_ids, dry_ids = select(batch.c.id), select(dry.c.id)
    source_bad = select(MillingProcessSource.id).where(
        MillingProcessSource.milling_process_id == MillingProcess.id,
        or_(MillingProcessSource.purchase_batch_id.is_not(None) & ~MillingProcessSource.purchase_batch_id.in_(batch_ids),
            MillingProcessSource.drying_lot_id.is_not(None) & ~MillingProcessSource.drying_lot_id.in_(dry_ids))).exists()
    mills = select(MillingProcess.id).where(MillingProcess.jasa_id.in_(own_ids),
        or_(MillingProcess.purchase_batch_id.is_(None), MillingProcess.purchase_batch_id.in_(batch_ids)),
        or_(MillingProcess.drying_lot_id.is_(None), MillingProcess.drying_lot_id.in_(dry_ids)), ~source_bad).cte('scope_mills')
    transfers = select(InternalTransfer.id).where(InternalTransfer.jasa_id.in_(own_ids),
        InternalTransfer.milling_process_id.in_(select(mills.c.id))).cte('scope_transfers')
    intakes = select(PkGudang2Intake.id).where(PkGudang2Intake.jasa_id.in_(own_ids),
        or_(PkGudang2Intake.internal_transfer_id.is_(None), PkGudang2Intake.internal_transfer_id.in_(select(transfers.c.id))),
        or_(PkGudang2Intake.pk_purchase_batch_id.is_(None), PkGudang2Intake.pk_purchase_batch_id.in_(select(pk.c.id)))).cte('scope_intakes')
    def header_aman(model, item, fk, nama):
        ada = select(item.id).where(getattr(item, fk) == model.id).exists()
        asing = select(item.id).where(getattr(item, fk) == model.id,
            or_(item.jasa_id.is_(None), ~item.jasa_id.in_(own_ids))).exists()
        return select(model.id).where(ada, ~asing).cte(nama)
    outs = header_aman(OutgoingRecord, OutgoingItem, 'outgoing_record_id', 'scope_outs')
    rets = header_aman(CustomerReturn, CustomerReturnItem, 'customer_return_id', 'scope_rets')
    rincian = select(ReturRincian.id).where(ReturRincian.outgoing_record_id.in_(select(outs.c.id))).cte('scope_rincian')
    queries = [select(literal('jasa').label('jenis'), own.c.id.label('id'), null().label('kode'))]
    for model, field, safe in [(PurchaseBatch,'kode_batch',batch), (PkPurchaseBatch,'kode_batch',pk),
            (DryingLot,'kode_lot',dry), (MillingProcess,'kode_proses',mills),
            (InternalTransfer,'kode_transfer',transfers), (PkGudang2Intake,None,intakes),
            (OutgoingRecord,None,outs), (CustomerReturn,None,rets), (ReturRincian,None,rincian)]:
        queries.append(select(literal(model.__tablename__), model.id,
            getattr(model, field) if field else null()).where(model.id.in_(select(safe.c.id))))
    tiket = table('timbangan_transaksi',column('id'),column('pelanggan_id'),column('jasa'),column('arah'))
    terkait = union_all(select(CustomerReturn.timbangan_transaksi_id).where(CustomerReturn.id.in_(select(rets.c.id))),
        select(ReturRincian.timbangan_transaksi_id).where(ReturRincian.id.in_(select(rincian.c.id))))
    queries.append(select(literal('timbangan_transaksi'),tiket.c.id,null()).where(or_(
        (tiket.c.pelanggan_id == reader.pelanggan_id) & (tiket.c.jasa == True) & tiket.c.arah.in_(('MASUK','RETUR_MASUK')),
        tiket.c.id.in_(terkait))))
    async with SessionLocal() as db:
        resources = defaultdict(set)
        codes = set()
        for kind, ident, code in (await db.execute(union_all(*queries))).all():
            resources[kind].add(ident)
            if code is not None:codes.add(code)
        ids = frozenset(resources.pop('jasa', ()))
        pols = (await db.execute(select(PolishingProcess.id,PolishingProcess.kode_proses,
            PolishingProcess.waktu_mulai,PolishingProcess.waktu_selesai)
            .where(PolishingProcess.jasa_id.in_(own_ids)))).all()
        polishing = {p.id:p for p in pols}
        unsafe = await _unsafe_polishing_sources(db,polishing,ids,frozenset(resources[PkGudang2Intake.__tablename__]))
        for row in pols:
            if row.id not in unsafe:
                resources[PolishingProcess.__tablename__].add(row.id)
                codes.add(row.kode_proses)
    # Stabilkan juga kunci resource kosong untuk kesetaraan capability lama.
    models = {m for m,_ in MODELS.values()} | {PkGudang2Intake,OutgoingRecord,CustomerReturn,ReturRincian}
    for model in models:resources[model.__tablename__]
    resources['timbangan_transaksi']
    return ReadScope(reader,ids,frozenset(codes),dict(resources))


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
        row = await db.scalar(select(model).where(dalam(db, model.id, scope.ids(model)),
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
