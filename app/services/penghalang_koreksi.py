"""Catatan hilir yang harus diperiksa manusia sebelum membetulkan asalnya."""
from sqlalchemy import select, or_
from app.models import InternalTransfer, OutgoingItem, OutgoingRecord
from app.penggilingan.gudang2.models import (PkGudang2Intake, PkTumpukanToSilo,
    PolishingSiloUsage, PolishingProcess, BerasKeSilo, HasilSampingKeSilo)
from app.penggilingan.inventory.models import FinishedGoodsStock, ByproductStock

MODEL = {'packing': FinishedGoodsStock, 'stok-samping': ByproductStock,
         'beras-silo': BerasKeSilo, 'samping-silo': HasilSampingKeSilo,
         'pk-silo': PkTumpukanToSilo}


def rincian(row, tipe):
    kode = getattr(row, 'kode_pindah', None) or f"{ {'packing':'Packing', 'stok-samping':'Stok hasil samping', 'beras-silo':'Beras ke silo', 'samping-silo':'Hasil samping ke silo', 'pk-silo':'PK ke silo'}[tipe]} #{row.id}"
    berat = getattr(row, 'berat_total_kg', None)
    if berat is None: berat = getattr(row, 'berat_kg', 0)
    return dict(kode=kode, jumlah=float(berat or 0),
        status=getattr(row, 'status', None) or 'tercatat',
        url=f'/koreksi-catatan/{tipe}/{row.id}')


async def daftar(db, jenis, id_):
    hasil = []
    if jenis == 'giling':
        rows = (await db.scalars(select(InternalTransfer).where(
            InternalTransfer.milling_process_id == id_, InternalTransfer.status == 'terkirim'))).all()
        hasil += [dict(kode=x.kode_transfer, jumlah=float(x.berat_kg), status=x.status,
                       url=f'/riwayat-transfer/{x.id}') for x in rows]
        items = (await db.scalars(select(OutgoingItem).where(
            OutgoingItem.milling_process_id == id_, OutgoingItem.item_type == 'pk_langsung'))).all()
        for x in items:
            rec = await db.get(OutgoingRecord, x.outgoing_record_id)
            if rec and rec.status != 'batal':
                hasil.append(dict(kode=rec.kode, jumlah=float(x.berat_kg), status=rec.status,
                                  url=f'/barang-keluar/{rec.id}'))
    elif jenis == 'sosoh':
        for tipe, model in MODEL.items():
            if tipe == 'pk-silo': continue
            kondisi = ((model.source_type == 'polishing') & (model.source_id == id_)
                       if tipe in ('packing','stok-samping') else model.polishing_process_id == id_)
            hasil += [rincian(x, tipe) for x in (await db.scalars(select(model).where(kondisi))).all()]
    elif jenis == 'transfer':
        intakes = (await db.scalars(select(PkGudang2Intake).where(
            PkGudang2Intake.internal_transfer_id == id_, PkGudang2Intake.dibatalkan_pada.is_(None)))).all()
        for it in intakes:
            moves = (await db.scalars(select(PkTumpukanToSilo).where(PkTumpukanToSilo.pk_gudang2_intake_id == it.id, PkTumpukanToSilo.dibatalkan_pada.is_(None)))).all()
            hasil += [rincian(x, 'pk-silo') for x in moves]
            silo_ids = [x.silo_id for x in moves] + ([it.silo_id] if it.silo_id else [])
            if silo_ids:
                rows = (await db.execute(select(PolishingSiloUsage, PolishingProcess).join(
                    PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id).where(
                    PolishingSiloUsage.silo_id.in_(silo_ids), or_(PolishingProcess.waktu_mulai >= it.waktu_masuk, PolishingSiloUsage.berat_akhir_kg.is_(None))))).all()
                hasil += [dict(kode=p.kode_proses, jumlah=float(u.berat_awal_kg or 0)+float(u.berat_masuk_kg or 0),
                    status=p.status, url=f'/proses-aktif/sosoh/{p.kode_proses}') for u,p in rows]
    return hasil
