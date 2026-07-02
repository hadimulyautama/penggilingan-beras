"""Helper audit trail (activity_logs)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog


async def log_activity(
    db: AsyncSession,
    *,
    table_name: str,
    record_id: int,
    action: str,
    changed_by: int | None = None,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    alasan: str | None = None,
) -> None:
    """Catat satu entri audit. Tidak commit — ikut transaksi pemanggil."""
    db.add(
        ActivityLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            alasan_perubahan=alasan,
        )
    )
