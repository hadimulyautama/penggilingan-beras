"""Helper identitas armada bersama untuk catatan bahan Operasional."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_core import Armada, normalisasi_nomor_polisi


async def armada_dari_nomor_polisi(
    db: AsyncSession, nomor: str | None, *, buat_baru: bool = True
) -> Armada | None:
    """Kaitkan catatan dengan master armada yang sama lintas aplikasi."""
    bersih = normalisasi_nomor_polisi(nomor)
    if not bersih:
        return None
    armada = (await db.execute(
        select(Armada).where(Armada.nomor_polisi == bersih)
    )).scalars().first()
    if armada is None and buat_baru:
        armada = Armada(nomor_polisi=bersih)
        db.add(armada)
        await db.flush()
    return armada
