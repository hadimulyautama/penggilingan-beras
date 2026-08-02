"""Simpan dokumen pengetahuan + potongannya ke DB. Dedup via konten_hash.

Idempoten: ingest ulang dokumen yang tak berubah = tanpa kerja. Bila isi
berubah, potongan lama diganti yang baru.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kantor.knowledge import chunker
from app.kantor.models import SopChunk, SopDokumen


async def ingest_dokumen(
    db: AsyncSession,
    *,
    judul: str,
    teks: str,
    kategori: str = "sop",
    ranah: str = "umum",
    sumber: str = "manual",
    sumber_ref: str | None = None,
) -> tuple[SopDokumen, bool]:
    """Simpan/segarkan satu dokumen. Return (dokumen, berubah?).

    Cari dokumen lama via sumber_ref (bila ada) atau judul. Bila hash isi sama →
    lewati (berubah=False). Bila berbeda/baru → tulis potongan.
    """
    h = chunker.konten_hash(teks)

    cond = SopDokumen.sumber_ref == sumber_ref if sumber_ref else SopDokumen.judul == judul
    doc = (await db.execute(select(SopDokumen).where(cond))).scalar_one_or_none()

    if doc and doc.konten_hash == h:
        return doc, False  # tak berubah

    if doc is None:
        doc = SopDokumen(judul=judul, kategori=kategori, ranah=ranah,
                         sumber=sumber, sumber_ref=sumber_ref, konten_hash=h)
        db.add(doc)
        await db.flush()      # dapatkan doc.id
    else:
        doc.judul, doc.kategori, doc.ranah = judul, kategori, ranah
        doc.sumber, doc.sumber_ref, doc.konten_hash = sumber, sumber_ref, h
        await db.execute(delete(SopChunk).where(SopChunk.dokumen_id == doc.id))

    for p in chunker.potong(teks):
        isi = f"[{p.judul_jalur}]\n{p.isi}" if p.judul_jalur else p.isi
        db.add(SopChunk(dokumen_id=doc.id, urutan=p.urutan, isi=isi))

    await db.commit()
    await db.refresh(doc)
    return doc, True
