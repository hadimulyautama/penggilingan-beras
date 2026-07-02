"""Helper pembuatan notifikasi (notifications)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def create_notification(
    db: AsyncSession,
    *,
    tipe: str,
    pesan: str,
    target_role: str | None = None,
    prioritas: str = "kuning",
    table_name: str | None = None,
    record_id: int | None = None,
) -> Notification:
    """Buat satu notifikasi. Tidak commit — ikut transaksi pemanggil."""
    notif = Notification(
        tipe=tipe,
        pesan=pesan,
        target_role=target_role,
        prioritas=prioritas,
        table_name=table_name,
        record_id=record_id,
    )
    db.add(notif)
    return notif
