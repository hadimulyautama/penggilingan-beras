"""Langkah operator pada skenario uji yang memang menghabiskan isi silo."""
from sqlalchemy import select
from app.models import MillingProcess, MillingProcessSource, SiloStorage, Silo
from app.penggilingan.gudang1.services.milling import tutup_silo_giling

async def pastikan_silo_kosong(db, *, user, kode_proses):
    """Operator memeriksa tiap silo dan secara eksplisit mencatat 0 kg."""
    nama = (await db.scalars(select(Silo.nama_silo).join(SiloStorage, SiloStorage.silo_id == Silo.id)
        .join(MillingProcessSource, MillingProcessSource.silo_storage_id == SiloStorage.id)
        .join(MillingProcess, MillingProcess.id == MillingProcessSource.milling_process_id)
        .where(MillingProcess.kode_proses == kode_proses, MillingProcessSource.berat_akhir_kg.is_(None))
        .distinct())).all()
    for silo in nama:
        await tutup_silo_giling(db, user=user, kode_proses=kode_proses,
            nama_silo=silo.replace('Silo ', ''), sisa_kg=0)
