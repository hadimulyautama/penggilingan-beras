"""Layar Stok — PK Gudang 1 yang masih ada, per lot giling.

Membaca saja. Tak ada tombol: stok tidak diubah dengan mengetik angkanya,
melainkan dengan mencatat pekerjaan yang mengubahnya (hasil giling, kirim ke
Gudang 2, jual langsung). Halaman yang membolehkan orang "membetulkan" stok
akan dipakai menutupi selisih — dan selisih yang ditutupi berhenti jadi
pertanyaan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import stok as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/stok")
async def halaman_stok(request: Request, akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        lot = await svc.pk_gudang1(db)
    return await render_laci(
        request, "stok.html", layar="stok",
        lot=lot,
        total=sum(l.tersedia for l in lot),
    )
