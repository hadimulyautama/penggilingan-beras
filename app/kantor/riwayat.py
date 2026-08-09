"""Ingatan percakapan bot Kantor — muat & simpan giliran per pengguna.

Tujuan: bot 'ingat' konteks obrolan sebelumnya (keunggulan yang dulu hanya ada
di Hermes). Dibatasi ketat agar konteks ke model tetap kecil = HEMAT TOKEN
(sesuai kebutuhan menekan biaya kredit):
  - hanya `BATAS_GILIRAN` giliran terakhir yang dimuat ke prompt,
  - isi tiap giliran dipotong `_MAKS_ISI` karakter,
  - baris lama di-prune, sisakan `_SIMPAN_MAKS` terbaru per pengguna.
"""
from __future__ import annotations

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.kantor.models import KantorChatRiwayat

BATAS_GILIRAN = 8    # giliran (user+assistant) yang disertakan ke konteks model
_MAKS_ISI = 800      # potong isi panjang agar tak membengkakkan token
_SIMPAN_MAKS = 40    # simpan maksimal N baris terakhir per pengguna (prune sisanya)


async def muat(tg_id: int | None, *, batas: int = BATAS_GILIRAN) -> list[dict]:
    """Ambil `batas` giliran terakhir → list {"role","content"} urut kronologis."""
    if not tg_id:
        return []
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(KantorChatRiwayat)
            .where(KantorChatRiwayat.telegram_user_id == tg_id)
            .order_by(KantorChatRiwayat.id.desc())
            .limit(batas)
        )).scalars().all()
    rows.reverse()  # kronologis (lama → baru)
    return [{"role": r.peran, "content": r.isi} for r in rows]


async def simpan(tg_id: int | None, peran: str, isi: str) -> None:
    """Simpan satu giliran (peran='user'/'assistant'); prune baris lama."""
    if not tg_id or not (isi or "").strip():
        return
    async with SessionLocal() as db:
        db.add(KantorChatRiwayat(
            telegram_user_id=tg_id, peran=peran, isi=isi.strip()[:_MAKS_ISI],
        ))
        await db.commit()
        # prune: buang baris di luar _SIMPAN_MAKS terbaru untuk pengguna ini
        batas_id = (await db.execute(
            select(KantorChatRiwayat.id)
            .where(KantorChatRiwayat.telegram_user_id == tg_id)
            .order_by(KantorChatRiwayat.id.desc())
            .offset(_SIMPAN_MAKS).limit(1)
        )).scalar_one_or_none()
        if batas_id is not None:
            await db.execute(delete(KantorChatRiwayat).where(
                KantorChatRiwayat.telegram_user_id == tg_id,
                KantorChatRiwayat.id <= batas_id,
            ))
            await db.commit()


async def lupakan(tg_id: int | None) -> int:
    """Hapus seluruh riwayat seorang pengguna (mis. perintah 'lupakan'). Jumlah dihapus."""
    if not tg_id:
        return 0
    async with SessionLocal() as db:
        res = await db.execute(delete(KantorChatRiwayat).where(
            KantorChatRiwayat.telegram_user_id == tg_id))
        await db.commit()
        return res.rowcount or 0
