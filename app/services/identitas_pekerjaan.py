"""Identitas kartu dari foreign key sumber; tak pernah menebak dari teks kartu."""
from collections import defaultdict

from sqlalchemy import select


async def lengkapi(db, baris):
    from app.models import (PurchaseBatch, PkPurchaseBatch, DryingLot,
                            MillingProcess, PolishingProcess, OutgoingRecord,
                            OutgoingItem)
    from app.services.jasa import nama_pemilik_banyak

    kode = {b.kode for b in baris if b.kode}
    sumber = defaultdict(set)
    # Kode dicocokkan persis. Tidak ada fallback berdasarkan awalan atau pemasok.
    for model, kolom in ((PurchaseBatch, PurchaseBatch.kode_batch),
                         (PkPurchaseBatch, PkPurchaseBatch.kode_batch),
                         (DryingLot, DryingLot.kode_lot),
                         (MillingProcess, MillingProcess.kode_proses),
                         (PolishingProcess, PolishingProcess.kode_proses)):
        for k, pemilik in (await db.execute(
                select(kolom, model.jasa_id).where(kolom.in_(kode)))).all():
            sumber[k].add(pemilik)
    for k, pemilik in (await db.execute(
            select(OutgoingRecord.kode, OutgoingItem.jasa_id)
            .join(OutgoingItem, OutgoingItem.outgoing_record_id == OutgoingRecord.id)
            .where(OutgoingRecord.kode.in_(kode)))).all():
        sumber[k].add(pemilik)
    for b in baris:
        if b.pemilik_ids is None and b.kode in sumber:
            b.pemilik_ids = tuple(sumber[b.kode])
        if b.pemilik_ids is None and b.jasa_id is not None:
            b.pemilik_ids = (b.jasa_id,)
    nama = await nama_pemilik_banyak(db, {j for b in baris for j in (b.pemilik_ids or ()) if j is not None})
    for b in baris:
        ids = b.pemilik_ids
        if ids:
            if len(set(ids)) == 1:
                b.jasa_id = ids[0]
                b.status_jasa = ids[0] is not None
            b.kepemilikan = ('pabrik' if set(ids) == {None} else
                             'campuran' if None in ids else 'jasa')
            b.pemilik_tampil = ' · '.join(nama.get(j, f'Pesanan #{j}') for j in sorted(set(ids) - {None})) or None
        elif b.status_jasa is not None:
            b.kepemilikan = 'jasa' if b.status_jasa else 'pabrik'
        else:
            b.kepemilikan = 'periksa'
