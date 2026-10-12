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

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import SessionLocal
from hmu_core.proses_db import ProsesTerpadu

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


@router.get("/produksi/proses")
async def produksi_proses(
    x_internal_token: str | None = Header(default=None),
    jenis: str | None = Query(default=None, max_length=40),
    status: str | None = Query(default=None, max_length=20),
    kode: str | None = Query(default=None, max_length=80),
    batas: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Baca daftar proses operasional bersama untuk Kantor (read-only)."""
    _pastikan_token(x_internal_token)
    async with SessionLocal() as db:
        q = (select(ProsesTerpadu)
             .options(selectinload(ProsesTerpadu.arus))
             .order_by(ProsesTerpadu.waktu_mulai.desc().nullslast(),
                       ProsesTerpadu.id.desc())
             .limit(batas))
        if jenis:
            q = q.where(ProsesTerpadu.jenis == jenis.strip().lower())
        if status:
            q = q.where(ProsesTerpadu.status == status.strip().lower())
        if kode:
            q = q.where(ProsesTerpadu.kode.ilike(f"%{kode.strip()}%"))
        rows = (await db.execute(q)).scalars().unique().all()

    return {"proses": [{
        "aplikasi": row.aplikasi,
        "tabel_sumber": row.tabel_sumber,
        "id_sumber": row.id_sumber,
        "kode": row.kode,
        "jenis": row.jenis,
        "status": row.status,
        "pemilik": {"jenis": row.jenis_pemilik, "id": row.id_pemilik,
                    "nama": row.nama_pemilik},
        "waktu_mulai": row.waktu_mulai.isoformat() if row.waktu_mulai else None,
        "waktu_selesai": row.waktu_selesai.isoformat() if row.waktu_selesai else None,
        "pelaksana_id": row.pelaksana_id,
        "referensi_asal": row.referensi_asal or [],
        "bahan": [{"komoditas": a.komoditas,
                   "atribut": a.atribut_produk or {}, "berat_kg": float(a.berat_kg),
                   "referensi": a.referensi, "lokasi_id": a.lokasi_id,
                   "detail": a.detail or {}}
                  for a in row.arus if a.arah == "bahan"],
        "hasil": [{"komoditas": a.komoditas,
                   "atribut": a.atribut_produk or {}, "berat_kg": float(a.berat_kg),
                   "referensi": a.referensi, "lokasi_id": a.lokasi_id,
                   "detail": a.detail or {}}
                  for a in row.arus if a.arah == "hasil"],
        "metadata": row.metadata_domain or {},
    } for row in rows]}
