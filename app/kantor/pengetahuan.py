"""Otak perusahaan untuk agen — CARI & SIMPAN pengetahuan (memakai knowledge/).

Membuat bot benar-benar "menambah pengetahuan seiring waktu": fakta/SOP/keputusan
yang disimpan bisa dicari lagi saat menjawab. Bukan model yang belajar — basis
pengetahuan yang tumbuh.

- cari_pengetahuan  : cari potongan pengetahuan relevan (read; retrieve.cari).
- simpan_pengetahuan: simpan catatan/fakta baru → permanen (ingest.ingest_dokumen).

Penyimpanan internal & reversibel (bisa dinonaktifkan/hapus di DB), jadi TIDAK
lewat gerbang tombol — beda dari aksi eksternal (Drive/email/kalender).
"""
from __future__ import annotations

from app.database import SessionLocal
from app.kantor.knowledge import ingest, retrieve

NAMA_TOOL = ("cari_pengetahuan", "simpan_pengetahuan")


async def cari(query: str, k: int = 5) -> str:
    if not (query or "").strip():
        return "Pertanyaan pencarian kosong."
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
        _doc, berubah = await ingest.ingest_dokumen(
            db, judul=judul.strip(), teks=isi.strip(),
            kategori="catatan", ranah="umum", sumber="bot")
    if not berubah:
        return f"'{judul}' sudah tersimpan (isi sama, tak diubah)."
    return f"✅ Pengetahuan disimpan: '{judul}'. Bisa kucari & pakai lagi kapan pun."


async def jalankan(nama_tool: str, args: dict) -> str:
    a = args or {}
    if nama_tool == "cari_pengetahuan":
        return await cari(a.get("query", "") or a.get("pertanyaan", ""))
    if nama_tool == "simpan_pengetahuan":
        return await simpan(a.get("judul", ""), a.get("isi", ""))
    return f"(tool '{nama_tool}' tak dikenal)"
