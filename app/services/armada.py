"""Helper identitas armada bersama untuk catatan bahan Operasional."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_core import Armada, normalisasi_nomor_polisi
from hmu_core.armada import validasi_nomor_polisi


async def armada_dari_nomor_polisi(
    db: AsyncSession, nomor: str | None, *, buat_baru: bool = True, dari_tiket_lama: bool = False
) -> Armada | None:
    """Kaitkan catatan dengan master armada yang sama lintas aplikasi."""
    bersih = normalisasi_nomor_polisi(nomor)
    if not bersih:
        return None
    try:
        bersih = validasi_nomor_polisi(nomor)
    except ValueError:
        if dari_tiket_lama or not buat_baru:
            return None  # Snapshot tiket lama utuh; jangan daftarkan penanda.
        raise
    armada = (await db.execute(
        select(Armada).where(Armada.nomor_polisi == bersih)
    )).scalars().first()
    if armada is None and buat_baru:
        armada = Armada(nomor_polisi=bersih)
        db.add(armada)
        await db.flush()
    return armada
