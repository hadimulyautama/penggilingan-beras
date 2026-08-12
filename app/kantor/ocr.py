"""Baca teks dari GAMBAR & PDF hasil SCAN via Claude vision (OCR).

Melengkapi baca_dokumen/unduh_teks yang hanya bisa teks digital: file .jpg/.png
dan PDF hasil scan (tanpa layer teks) kini bisa "dibaca" dengan mengirim
gambar/PDF ke model multimodal. Dipakai on-demand lewat tool `baca_gambar`, dan
sebagai fallback saat ingest menemui file tanpa teks.

Model = settings.agent_model (punya kemampuan vision). Read-only, tak lewat gerbang.
"""
from __future__ import annotations

import asyncio
import base64
import logging

from app.ai import guard
from app.config import settings
from app.kantor.drive import operasi as O

log = logging.getLogger(__name__)

NAMA_TOOL = ("baca_gambar",)

_IMG = ("image/jpeg", "image/png", "image/gif", "image/webp")
_PDF = "application/pdf"

_PROMPT = (
    "Ekstrak SELURUH teks yang terlihat pada dokumen/gambar ini, apa adanya "
    "(verbatim, jangan menerjemahkan/merapikan). Pertahankan struktur tabel "
    "sebagai 'kolom | kolom'. Untuk dokumen identitas (KTP/KK/paspor/BPJS), "
    "cantumkan tiap field beserta nilainya (mis. NIK, Nama, Tempat/Tgl Lahir). "
    "Keluarkan HANYA teksnya, tanpa komentar. Bila tak ada teks terbaca, jawab "
    "persis: (tidak ada teks terbaca)."
)


def bisa_ocr(mime: str) -> bool:
    return mime in _IMG or mime == _PDF


async def ocr_bytes(data: bytes, mime: str, nama: str = "") -> str:
    """Kirim bytes gambar/PDF ke model → teks hasil OCR. '' bila gagal."""
    b64 = base64.standard_b64encode(data).decode("ascii")
    if mime == _PDF:
        blok = {"type": "document",
                "source": {"type": "base64", "media_type": _PDF, "data": b64}}
    elif mime in _IMG:
        blok = {"type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64}}
    else:
        return ""
    try:
        r = await guard.panggil(
            pemanggil="ocr",
            model=settings.agent_model, max_tokens=8000,
            messages=[{"role": "user", "content": [blok, {"type": "text", "text": _PROMPT}]}],
        )
        teks = "".join(b.text for b in r.content if b.type == "text").strip()
        return "" if teks == "(tidak ada teks terbaca)" else teks
    except Exception:  # noqa: BLE001
        log.warning("OCR gagal untuk %s", nama or mime, exc_info=True)
        return ""


async def baca_gambar(nama: str) -> str:
    """Tool: baca isi sebuah file GAMBAR / PDF-scan lewat OCR."""
    cl = O._client()
    if cl is None:
        return O.DRIVE_OFF
    if not (nama or "").strip():
        return "Sebutkan nama file gambar/scan yang mau dibaca."

    def _cari():
        semua = [x for x in cl.cari(nama, maks=25) if not x.is_folder]
        return [x for x in semua if x.nama == nama] or semua

    kand = await asyncio.to_thread(_cari)
    if not kand:
        return f"File '{nama}' tidak ditemukan."
    if len(kand) > 1:
        return ("Beberapa file cocok — sebut nama PERSIS:\n"
                + "\n".join(f"• {x.nama}" for x in kand[:10]))
    f = kand[0]
    if not bisa_ocr(f.mime):
        return f"'{f.nama}' bukan gambar/PDF — untuk dokumen teks pakai baca_dokumen/baca_sheet."

    def _unduh():
        return cl._service().files().get_media(fileId=f.id, supportsAllDrives=True).execute()

    try:
        data = await asyncio.to_thread(_unduh)
    except Exception as e:  # noqa: BLE001
        return f"Gagal mengunduh '{f.nama}': {e}"
    teks = await ocr_bytes(data, f.mime, f.nama)
    if not teks:
        return f"(Tak ada teks yang bisa dibaca dari '{f.nama}'.)"
    return f"📄 {f.nama} (via OCR):\n{teks}"


async def jalankan(nama_tool: str, args: dict) -> str:
    a = args or {}
    if nama_tool == "baca_gambar":
        return await baca_gambar(a.get("nama", ""))
    return f"(tool '{nama_tool}' tak dikenal)"
