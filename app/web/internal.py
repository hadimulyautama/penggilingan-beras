"""API internal PRODUKSI — satu-satunya pintu baca data pabrik untuk Kantor AI.

Alasan ada: Kantor AI berpisah repo & service. Ia TIDAK boleh mengimpor kode
produksi lagi (`app.ai.agent`, `app.services.analytics`, `app.services.dashboard`),
tapi tetap perlu tiga hal itu. Jadi produksi menyediakannya sebagai JSON kecil
ber-token, Kantor memanggilnya lewat `klien_produksi`.

Keamanan:
  - Aktif hanya bila env `INTERNAL_API_TOKEN` diisi (kosong → 404, seperti /dashboard).
  - Setiap permintaan wajib membawa header `X-Internal-Token` yang sama persis.
  - READ-ONLY: agent memang tak punya kemampuan tulis; tak ada endpoint tulis.
  - Data uang (HPP/harga) hanya keluar bila pemanggil mengirim financial=true —
    keputusan hak akses tetap di sisi Kantor (RBAC-nya), sama seperti sebelum pisah.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.database import SessionLocal

router = APIRouter(prefix="/internal", tags=["internal"])
log = logging.getLogger("web.internal")


def _pastikan_token(token: str | None) -> None:
    if not settings.internal_api_token:
        raise HTTPException(status_code=404, detail="API internal tidak aktif.")
    if not token or not hmac.compare_digest(token, settings.internal_api_token):
        raise HTTPException(status_code=403, detail="Token internal tidak valid.")


class TanyaIn(BaseModel):
    pertanyaan: str
    role: str = "admin"
    financial: bool = False


class HppIn(BaseModel):
    harga_gabah: float | None = None
    rendemen_persen: float | None = None
    kondisi: str = "basah"
    langsung_silo: bool = False
    berat_bahan: float | None = None
    berat_hasil: float | None = None


@router.post("/produksi/tanya")
async def produksi_tanya(
    body: TanyaIn, x_internal_token: str | None = Header(default=None)
) -> dict:
    """Delegasikan pertanyaan produksi ke AI Agent pabrik (read-only)."""
    _pastikan_token(x_internal_token)
    from app.ai import agent as agen_produksi

    pertanyaan = (body.pertanyaan or "").strip()
    if not pertanyaan:
        raise HTTPException(status_code=422, detail="Pertanyaan kosong.")
    reply = await agen_produksi.run_agent(
        text=pertanyaan, role=body.role, financial=body.financial,
    )
    return {"teks": reply.text or ""}


# Rute `/produksi/hpp` (simulasi what-if) DIBUANG 28 September 2026 bersama
# seluruh HPP: harga keluar dari Pos Produksi (keputusan pemilik). Yang
# memanggilnya dari luar akan menerima 404, dan itu jawaban yang benar —
# simulasi yang memakai tarif yang tak lagi dipelihara lebih buruk daripada
# tak ada simulasi.


@router.get("/produksi/operasional")
async def produksi_operasional(
    x_internal_token: str | None = Header(default=None)
) -> dict:
    """Ringkasan operasional hari ini (bahan briefing pagi Kantor)."""
    _pastikan_token(x_internal_token)
    from app.services.dashboard import dashboard_data

    async with SessionLocal() as db:
        data = await dashboard_data(db)
    return data.get("operasional", {}) or {}
