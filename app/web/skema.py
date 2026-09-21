"""Apakah skema basis data sudah selaras dengan kode yang sedang berjalan?

Temuan QA X-04, 11 September 2026.

Ketiga `/health` menjawab "ok" tanpa pernah melihat skemanya. Layanan yang
menyala di atas skema yang tertinggal satu migrasi akan menerima pencatatan
dan menyimpannya salah — atau gagal di kolom yang tak ada, satu per satu,
dengan pesan berbeda-beda yang tak menunjuk ke satu sebab.

Yang dibaca di sini hanya tabel versi alembic: revisi yang TERCATAT di basis
data, dibandingkan dengan revisi HEAD yang dikenal kode ini. Murah, dan cukup
untuk menjawab pertanyaan yang benar-benar ingin diketahui orang saat sesuatu
aneh terjadi: "apakah ini deploy yang skemanya belum selesai?"
"""
from __future__ import annotations

import logging
import pathlib

from sqlalchemy import text

from app.database import SessionLocal

log = logging.getLogger("web.skema")

#: Tabel versi milik chain ini.
TABEL_VERSI = "alembic_version"


def revisi_berkas() -> list[str]:
    """Seluruh revisi yang dikenal kode ini, urut dari yang tertua.

    Dibaca dari nama berkas, bukan dengan memuat alembic: memuat alembic saat
    melayani /health berarti biaya dan satu cara baru untuk gagal. Nama
    berkasnya berawalan nomor urut empat digit dan sama persis dengan
    `revision` di dalamnya, jadi urutan abjad = urutan rantai.
    """
    akar = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
    try:
        return sorted(p.stem for p in akar.glob("0*.py"))
    except Exception:  # noqa: BLE001
        return []


def _head_dari_berkas() -> str | None:
    """Revisi HEAD menurut berkas migrasi di image ini."""
    berkas = revisi_berkas()
    return berkas[-1] if berkas else None


async def keadaan() -> dict:
    """{'revisi': …, 'head': …, 'selaras': bool} — tak pernah melempar."""
    head = _head_dari_berkas()
    try:
        async with SessionLocal() as db:
            revisi = (await db.execute(
                text(f"SELECT version_num FROM {TABEL_VERSI}")
            )).scalars().first()
    except Exception as e:  # noqa: BLE001 — basis data tak terjangkau
        log.warning("Revisi skema tak terbaca: %s", e)
        return {"revisi": None, "head": head, "selaras": False,
                "galat": type(e).__name__}
    return {"revisi": revisi, "head": head,
            "selaras": bool(revisi and head and revisi == head)}
