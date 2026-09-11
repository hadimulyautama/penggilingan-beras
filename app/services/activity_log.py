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
    aksi: str | None = None,
) -> None:
    """Catat satu entri audit. Tidak commit — ikut transaksi pemanggil.

    `aksi` menyebutkan MAKSUD-nya, dan itu yang dipakai pembatalan untuk
    memilih penangan. Tanpanya pembatalan menebak dari nama tabel & kolom —
    dan tebakan itu salah persis pada kasus yang paling mudah keliru: "ubah
    target kadar air" dan "gabungkan batch ke lot" sama-sama UPDATE pada
    `drying_lots`.

    Boleh kosong, dan sebagian besar pemanggil memang belum menyebutkannya:
    yang wajib hanya aksi yang MAKSUDNYA tak bisa dibaca dari tabel & kolom.
    """
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
            aksi=aksi,
        )
    )
