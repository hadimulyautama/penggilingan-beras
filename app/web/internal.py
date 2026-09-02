"""API internal PRODUKSI — satu-satunya pintu baca data pabrik untuk Kantor AI.

Alasan ada: Kantor AI berpisah repo & service. Ia TIDAK boleh mengimpor kode
produksi lagi (`app.ai.agent`, `app.services.analytics`, `app.services.dashboard`),
tapi tetap perlu tiga hal itu. Jadi produksi menyediakannya sebagai JSON kecil
ber-token, Kantor memanggilnya lewat `klien_produksi`.

Keamanan:
  - Aktif hanya bila env `INTERNAL_API_TOKEN` diisi (kosong → 404, seperti /dashboard).
  - Setiap permintaan wajib membawa header `X-Internal-Token` yang sama persis.
  - READ-ONLY: agent dipanggil dengan allow_write=False; tak ada endpoint tulis.
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
    role: str = "staff"
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
        text=pertanyaan, role=body.role, financial=body.financial, allow_write=False,
    )
    return {"teks": reply.text or ""}


@router.post("/produksi/hpp")
async def produksi_hpp(
    body: HppIn, x_internal_token: str | None = Header(default=None)
) -> dict:
    """Simulasi what-if HPP (tarif biaya terkini). Tak menyentuh data batch."""
    _pastikan_token(x_internal_token)
    from app.services import analytics

    teks = analytics.simulasi_hpp(
        body.harga_gabah, body.rendemen_persen,
        kondisi=body.kondisi, langsung_silo=body.langsung_silo,
        berat_bahan=body.berat_bahan, berat_hasil=body.berat_hasil,
    )
    return {"teks": teks}


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
