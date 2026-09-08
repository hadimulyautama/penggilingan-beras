"""Layar "Berjalan": pekerjaan yang belum tertutup, dan bisa ditutup dari sini.

Isinya disusun `app.services.berjalan`. Yang dikerjakan di sini hanya
menyajikannya — dan satu hal yang membuatnya berbeda dari laporan: tiap baris
menaut ke aksi yang MENUTUPnya, jadi menekan baris membuka formulir yang
benar dalam satu ketukan. Laporan memberi tahu; layar ini menyelesaikan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import berjalan as svc
from app.web.security import butuh_akun
from app.web.tampilan import render

router = APIRouter(tags=["webapp"])


@router.get("/berjalan")
async def halaman_berjalan(request: Request, akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)
    return render(
        request, "berjalan.html",
        # Mesin yang menyala, dan gabah yang sudah punya tempat tetapi tak
        # sedang diapa-apakan. Antrean tak ikut ke sini — ia punya layarnya
        # sendiri.
        berjalan=b.berjalan, transit=b.transit,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        MENUNGGU=b.jumlah_menunggu, BERJALAN=b.jumlah_berjalan,
        KEPUTUSAN=b.jumlah_keputusan,
        lama=svc._lama,
    )
