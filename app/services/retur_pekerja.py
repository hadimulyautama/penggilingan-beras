"""Periksa tiket yang selesai tanpa bergantung pada kunjungan halaman retur."""
import asyncio
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.penggilingan.inventory.models import ReturRincian
from app.services.retur_penerimaan import periksa_dan_terima

log = logging.getLogger(__name__)


async def sekali():
    async with SessionLocal() as db:
        ids = (await db.scalars(select(ReturRincian.id).where(
            ReturRincian.outgoing_record_id.is_not(None),
            ReturRincian.customer_return_id.is_(None),
            ReturRincian.status_pemeriksaan != 'dibatalkan')
            .order_by(ReturRincian.id))).all()
    # Satu transaksi per penerimaan: masalah satu tiket tidak menahan seluruh
    # pengajuan. Kunci dan indeks unik membuat beberapa replika tetap aman.
    for identitas in ids:
        async with SessionLocal() as db:
            try:
                await periksa_dan_terima(db, identitas)
                await db.commit()
            except ValueError:
                await db.rollback()
                log.warning('Pengajuan retur %s belum memenuhi validasi sumber/tiket.', identitas)
            except Exception:
                await db.rollback()
                log.exception('Pemeriksaan pengajuan retur %s gagal.', identitas)


async def jalankan():
    log.info('Pekerja pemeriksaan retur aktif (setiap 10 detik).')
    while True:
        try:
            await sekali()
        except Exception:
            log.exception('Pekerja pemeriksaan retur gagal membaca pengajuan.')
        await asyncio.sleep(10)
