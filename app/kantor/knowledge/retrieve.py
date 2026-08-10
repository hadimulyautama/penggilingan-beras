"""Cari potongan pengetahuan relevan untuk konteks peran.

Fase awal: pencarian kata (skor = jumlah kata kunci yang cocok) — gratis, tanpa
model/ekstensi, jalan di Postgres mana pun. Antarmuka `cari()` dibuat stabil
agar backend makna (embedding/pgvector) bisa ditambahkan tanpa ubah pemanggil.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Integer, case, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kantor.models import SopChunk, SopDokumen

_STOP = {"yang", "dan", "atau", "di", "ke", "dari", "untuk", "pada", "dengan",
         "ini", "itu", "apa", "bagaimana", "adalah", "the", "a"}


@dataclass
class Cuplikan:
    dokumen: str
    isi: str
    skor: int


def _kata_kunci(q: str) -> list[str]:
    kata = [w for w in re.split(r"\W+", q.lower()) if len(w) > 2 and w not in _STOP]
    # unik, jaga urutan
    seen: set[str] = set()
    return [w for w in kata if not (w in seen or seen.add(w))]


async def cari(
    db: AsyncSession, query: str, *, ranah: str | None = None,
    tanpa_ranah: set[str] | None = None, k: int = 5,
) -> list[Cuplikan]:
    """Kembalikan hingga `k` potongan paling relevan dengan `query`.

    Bila `ranah` diisi, batasi ke dokumen ranah itu + 'umum'. Bila `tanpa_ranah`
    diisi, KECUALIKAN dokumen ber-ranah tsb (mis. {'rahasia'} untuk staff). Hasil
    kosong bila tak ada kata kunci yang cocok.
    """
    kk = _kata_kunci(query)
    if not kk:
        return []

    skor = sum(
        (cast(SopChunk.isi.ilike(f"%{w}%"), Integer) for w in kk),
        cast(case((SopChunk.isi.is_(None), 0), else_=0), Integer),
    )

    stmt = select(SopChunk.isi, SopDokumen.judul, skor.label("skor")).join(
        SopDokumen, SopChunk.dokumen_id == SopDokumen.id
    )
    if ranah:
        stmt = stmt.where(or_(SopDokumen.ranah == ranah, SopDokumen.ranah == "umum"))
    if tanpa_ranah:
        stmt = stmt.where(SopDokumen.ranah.notin_(tuple(tanpa_ranah)))
    stmt = stmt.where(SopDokumen.status == "aktif").where(skor > 0)
    stmt = stmt.order_by(skor.desc(), SopChunk.id).limit(k)

    rows = (await db.execute(stmt)).all()
    return [Cuplikan(dokumen=judul, isi=isi, skor=int(s)) for isi, judul, s in rows]
