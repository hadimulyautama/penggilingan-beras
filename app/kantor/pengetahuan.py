"""Otak perusahaan untuk agen — CARI & SIMPAN pengetahuan (memakai knowledge/).

Membuat bot benar-benar "menambah pengetahuan seiring waktu": fakta/SOP/keputusan
yang disimpan bisa dicari lagi saat menjawab. Bukan model yang belajar — basis
pengetahuan yang tumbuh.

- cari_pengetahuan  : cari potongan pengetahuan relevan (read).
- simpan_pengetahuan: simpan catatan/fakta baru → permanen.

Pencarian: SEMANTIK (Voyage AI embedding + cosine) bila VOYAGE_API_KEY terpasang —
paham MAKNA, bukan cuma kecocokan kata. Bila Voyage tak ada/gagal → jatuh mulus ke
pencarian keyword (retrieve.cari) sehingga tak pernah rusak.

Penyimpanan internal & reversibel (bisa dinonaktifkan/hapus di DB), jadi TIDAK
lewat gerbang tombol — beda dari aksi eksternal (Drive/email/kalender).
"""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor.knowledge import embed as emb
from app.kantor.knowledge import ingest, retrieve
from app.kantor.models import SopChunk, SopDokumen

log = logging.getLogger(__name__)

NAMA_TOOL = ("cari_pengetahuan", "simpan_pengetahuan")

# Ambang cosine minimal agar sebuah cuplikan dianggap relevan (0..1).
# voyage-3.5-lite: senada ~0.49, beda topik ~0.33 → 0.40 memisah bersih.
_AMBANG = 0.40


async def _cari_semantik(query: str, k: int) -> list[tuple[str, str]]:
    """Cari via embedding. Kembalikan [(judul, isi), ...] top-k yang cukup mirip;
    [] bila belum ada embedding / tak ada yang lolos ambang (pemanggil lalu
    memakai keyword sebagai jaring pengaman)."""
    qv = await asyncio.to_thread(emb.embed, [query], input_type="query")
    if not qv:
        return []
    qv = qv[0]
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(SopChunk.isi, SopChunk.embedding, SopDokumen.judul)
            .join(SopDokumen, SopChunk.dokumen_id == SopDokumen.id)
            .where(SopDokumen.status == "aktif", SopChunk.embedding.isnot(None))
        )).all()
    skor: list[tuple[float, str, str]] = []
    for isi, emb_json, judul in rows:
        try:
            vec = json.loads(emb_json)
        except (TypeError, ValueError):
            continue
        skor.append((emb.kemiripan(qv, vec), judul, isi))
    skor.sort(key=lambda s: s[0], reverse=True)
    return [(judul, isi) for sk, judul, isi in skor[:k] if sk >= _AMBANG]


async def cari(query: str, k: int = 5) -> str:
    if not (query or "").strip():
        return "Pertanyaan pencarian kosong."
    # 1) Coba semantik (kalau Voyage terpasang).
    if emb.terkonfigurasi():
        try:
            hasil = await _cari_semantik(query, k)
            if hasil:
                baris = [f"• ({j}) {i[:400]}" for j, i in hasil]
                return f"🧠 {len(hasil)} pengetahuan relevan (semantik):\n" + "\n".join(baris)
        except Exception:  # noqa: BLE001 — embedding gagal → fallback keyword
            log.warning("cari semantik gagal, fallback keyword", exc_info=True)
    # 2) Jaring pengaman keyword — jalan bila semantik mati/tak nemu/tak terpasang.
    async with SessionLocal() as db:
        hits = await retrieve.cari(db, query, k=k)
    if not hits:
        return (f"Tak ada pengetahuan tersimpan yang cocok '{query}'. "
                "Kalau ini fakta penting, minta pengguna agar kamu simpan (simpan_pengetahuan).")
    baris = [f"• ({h.dokumen}) {h.isi[:400]}" for h in hits]
    return f"🧠 {len(hits)} pengetahuan relevan:\n" + "\n".join(baris)


async def simpan(judul: str, isi: str) -> str:
    if not (judul or "").strip() or not (isi or "").strip():
        return "Judul dan isi pengetahuan wajib diisi."
    async with SessionLocal() as db:
        doc, berubah = await ingest.ingest_dokumen(
            db, judul=judul.strip(), teks=isi.strip(),
            kategori="catatan", ranah="umum", sumber="bot")
        if not berubah:
            return f"'{judul}' sudah tersimpan (isi sama, tak diubah)."
        # Embed chunk-nya biar bisa dicari secara makna (kalau Voyage terpasang).
        if emb.terkonfigurasi():
            try:
                chunks = (await db.execute(
                    select(SopChunk).where(SopChunk.dokumen_id == doc.id)
                )).scalars().all()
                if chunks:
                    vecs = await asyncio.to_thread(
                        emb.embed, [c.isi for c in chunks], input_type="document")
                    for c, v in zip(chunks, vecs):
                        c.embedding = json.dumps(v)
                    await db.commit()
            except Exception:  # noqa: BLE001 — gagal embed → tetap tersimpan (keyword jalan)
                log.warning("embed saat simpan gagal (tetap tersimpan)", exc_info=True)
    return f"✅ Pengetahuan disimpan: '{judul}'. Bisa kucari & pakai lagi kapan pun."


async def jalankan(nama_tool: str, args: dict) -> str:
    a = args or {}
    if nama_tool == "cari_pengetahuan":
        return await cari(a.get("query", "") or a.get("pertanyaan", ""))
    if nama_tool == "simpan_pengetahuan":
        return await simpan(a.get("judul", ""), a.get("isi", ""))
    return f"(tool '{nama_tool}' tak dikenal)"
