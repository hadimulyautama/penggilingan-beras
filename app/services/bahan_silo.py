"""Data tampilan sumber giling, dibaca borongan tanpa mengubah bahan atau stok."""
from sqlalchemy import select, func
from app.models import MillingProcessSource, SiloStorage, Silo, DryingLot, PurchaseBatch
from app.services.berjalan import _kg


async def sumber_giling_banyak(db, ids):
    rows = (await db.execute(select(MillingProcessSource, Silo.nama_silo,
        func.coalesce(DryingLot.kode_lot, PurchaseBatch.kode_batch))
        .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
        .join(Silo, Silo.id == SiloStorage.silo_id)
        .outerjoin(DryingLot, DryingLot.id == MillingProcessSource.drying_lot_id)
        .outerjoin(PurchaseBatch, PurchaseBatch.id == MillingProcessSource.purchase_batch_id)
        .where(MillingProcessSource.milling_process_id.in_(ids))
        .order_by(MillingProcessSource.id))).all()
    hasil = {}
    for s, nama, asal in rows:
        hasil.setdefault(s.milling_process_id, []).append(dict(
            nama=nama, unit='catatan sumber', berat=_kg(s.berat_kg) if s.berat_kg is not None else 'Belum diketahui',
            status='Dilepaskan' if s.berat_akhir_kg is not None else 'Pelepasan belum dicatat',
            angka=[('Awal', _kg(s.berat_kg) if s.berat_kg is not None else 'Belum diketahui'),
                   ('Tambahan', 'Tidak dipisahkan'),
                   ('Sisa akhir', _kg(s.berat_akhir_kg) if s.berat_akhir_kg is not None else 'Belum dicatat'),
                   ('Terpakai', _kg(s.berat_terpakai_kg) if s.berat_terpakai_kg is not None else 'Belum tercatat')],
            bahan=[dict(nama='Gabah', berat='')],
            sumber=[dict(nama=asal or 'Asal belum tercatat', berat='', ket='')],
            catatan='Setiap catatan adalah sumber gabah yang terikat ke proses. Tambahan per pemakaian silo belum dipisahkan; sumber dengan silo yang sama tetap ditampilkan terpisah.'))
    return hasil
