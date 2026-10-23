"""Penyajian QC batch asal: baca catatan asli, tanpa skor atau transaksi baru."""
from sqlalchemy import select

from app.models import (InternalTransfer, MillingProcess, PurchaseBatchQc,
                        PurchaseBatchQcSample, User)
from app.services.setelan import fitur_mutu


def _label(nilai):
    return nilai.replace('_', ' ').capitalize() if nilai else 'Belum tercatat'


def _air(nilai):
    return f'{float(nilai):g}%'.replace('.', ',') if nilai is not None else 'Belum tercatat'


async def dari_batches(db, batches):
    if not await fitur_mutu(db):
        return None
    batches = list({b.id: b for b in batches}.values())
    ids = [b.id for b in batches]
    headers = {q.purchase_batch_id: q for q in (await db.scalars(
        select(PurchaseBatchQc).where(PurchaseBatchQc.purchase_batch_id.in_(ids)))).all()} if ids else {}
    samples = {}
    if headers:
        rows = (await db.execute(select(PurchaseBatchQcSample, User.nama)
            .outerjoin(User, User.id == PurchaseBatchQcSample.input_by)
            .where(PurchaseBatchQcSample.purchase_batch_qc_id.in_([q.id for q in headers.values()]))
            .order_by(PurchaseBatchQcSample.nomor_sampel, PurchaseBatchQcSample.id))).all()
        for s, nama in rows:
            samples.setdefault(s.purchase_batch_qc_id, []).append((s, nama))
    hasil = []
    for b in batches:
        q = headers.get(b.id)
        rows = samples.get(q.id, []) if q else []
        # Header QC lama tetap sah meskipun belum memiliki tabel sampel.
        if q and not rows:
            rows = [(q, await db.scalar(select(User.nama).where(User.id == q.input_by)))]
        catatan = []
        for s, nama in rows:
            lamur = ('Tidak berlaku untuk gabah kering' if b.kondisi_gabah == 'kering' else
                     'Belum tercatat' if s.lamur is None else
                     'Tidak' if not s.lamur else
                     'Ya · ' + (f'{s.jumlah_sak_lamur} sak' if s.jumlah_sak_lamur is not None else 'jumlah sak belum tercatat'))
            catatan.append(dict(nomor=getattr(s, 'nomor_sampel', None), waktu=s.created_at,
                pencatat=nama or 'Pencatat belum tercatat',
                air1=_air(getattr(s, 'kadar_air_1', None)), air2=_air(getattr(s, 'kadar_air_2', None)),
                lamur=lamur, hijau=_label(s.biji_hijau), densiti=_label(s.densiti)))
        hasil.append(dict(kode=b.kode_batch, kondisi=b.kondisi_gabah, catatan=catatan))
    return hasil


async def dari_giling(db, proses):
    from app.penggilingan.gudang1.services.milling import sumber_batch
    batches = [b for b, _, _ in await sumber_batch(db, proses)] if proses else []
    return await dari_batches(db, batches)


async def dari_pk(db, *, kode=None, intake_id=None):
    from app.penggilingan.gudang2.models import PkGudang2Intake
    proses = None
    if intake_id is not None:
        intake = await db.get(PkGudang2Intake, intake_id)
        transfer = await db.get(InternalTransfer, intake.internal_transfer_id) if intake and intake.internal_transfer_id else None
        proses = await db.get(MillingProcess, transfer.milling_process_id) if transfer else None
    elif kode:
        proses = await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses == kode))
    return await dari_giling(db, proses)
