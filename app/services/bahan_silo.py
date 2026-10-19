"""Data tampilan sumber giling, dibaca borongan tanpa mengubah bahan atau stok."""
from sqlalchemy import select, func
from app.models import MillingProcessSource, SiloStorage, Silo, DryingLot, PurchaseBatch, ActivityLog
from decimal import Decimal


def kg_rinci(n):
    """Pertahankan pecahan agar sisa positif tidak tampak sebagai kosong."""
    n = Decimal(str(n))
    if n == 0:
        n = Decimal(0)
    return format(n, ",.3f").rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".") + " kg"


async def sumber_giling_banyak(db, ids):
    rows = (await db.execute(select(MillingProcessSource, Silo.nama_silo,
        func.coalesce(DryingLot.kode_lot, PurchaseBatch.kode_batch))
        .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
        .join(Silo, Silo.id == SiloStorage.silo_id)
        .outerjoin(DryingLot, DryingLot.id == MillingProcessSource.drying_lot_id)
        .outerjoin(PurchaseBatch, PurchaseBatch.id == MillingProcessSource.purchase_batch_id)
        .where(MillingProcessSource.milling_process_id.in_(ids))
        .order_by(MillingProcessSource.id))).all()
    # Audit pembebasan menyimpan sisa seluruh silo; sisa pada tiap sumber
    # hanyalah pembagian FIFO dan bukan sisa pemakaian terakhir silo.
    per_silo = {}
    pemilik_sumber = {}
    for s, nama, _ in rows:
        kunci = (s.milling_process_id, nama)
        per_silo.setdefault(kunci, []).append(s)
        pemilik_sumber[s.id] = kunci
    audit = {}
    if pemilik_sumber:
        logs = (await db.scalars(select(ActivityLog).where(
            ActivityLog.table_name == 'milling_process_sources',
            ActivityLog.aksi == 'tutup_silo_giling',
            ActivityLog.record_id.in_(list(pemilik_sumber)),
            ActivityLog.dibatalkan_pada.is_(None)
        ).order_by(ActivityLog.id))).all()
        for log in logs:
            audit[pemilik_sumber[log.record_id]] = log
    hasil = {}
    for s, nama, asal in rows:
        hasil.setdefault(s.milling_process_id, []).append(dict(
            nama=nama, total_kg=float(s.berat_kg) if s.berat_kg is not None else None, tambahan_kg=None, unit='catatan sumber', berat=kg_rinci(s.berat_kg) if s.berat_kg is not None else 'Belum diketahui',
            status='Dilepaskan' if s.berat_akhir_kg is not None else 'Pelepasan belum dicatat',
            angka=[('Awal', kg_rinci(s.berat_kg) if s.berat_kg is not None else 'Belum diketahui'),
                   ('Tambahan', 'Tidak dipisahkan'),
                   ('Sisa akhir', kg_rinci(s.berat_akhir_kg) if s.berat_akhir_kg is not None else 'Belum dicatat'),
                   ('Terpakai', kg_rinci(s.berat_terpakai_kg) if s.berat_terpakai_kg is not None else 'Belum tercatat')],
            bahan=[dict(nama='Gabah', berat='')],
            sumber=[dict(nama=asal or 'Asal belum tercatat', berat='', ket='')],
            catatan='Setiap catatan adalah sumber gabah yang terikat ke proses. Tambahan per pemakaian silo belum dipisahkan; sumber dengan silo yang sama tetap ditampilkan terpisah.'))
    for pid, kelompok in hasil.items():
        for nama in {g['nama'] for g in kelompok}:
            semua = per_silo[(pid, nama)]
            akhir = [g for g in kelompok if g['nama'] == nama][-1]
            if any(s.berat_akhir_kg is None for s in semua):
                akhir['ringkasan_sisa'] = 'Belum dicatat'
                akhir['ringkasan_status'] = 'Masih terikat proses'
                continue
            log = audit.get((pid, nama))
            sisa = None
            if log and all(s.created_at <= log.waktu_perubahan for s in semua):
                try:
                    from decimal import Decimal, InvalidOperation
                    n = Decimal(log.new_value)
                    if n.is_finite() and n >= 0:
                        sisa = n
                except (InvalidOperation, TypeError):
                    pass
            if sisa is None and (len(semua) == 1 or all(float(s.berat_akhir_kg) == 0 for s in semua)):
                sisa = sum(float(s.berat_akhir_kg) for s in semua)
            akhir['ringkasan_sisa'] = kg_rinci(sisa) if sisa is not None else 'Belum dapat dipastikan'
            akhir['ringkasan_status'] = 'Dilepaskan'
    return hasil
