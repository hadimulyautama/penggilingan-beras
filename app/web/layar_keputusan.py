"""Layar "Menunggu keputusan" — kerja MEJA, bukan kerja gudang.

Barisnya pernah menumpang di Antrian tunggu, dan itu menyalahi aturan yang
paling sering diucapkan pemilik: **begitu gabah punya tempat, ia keluar dari
antrean.** Gabah di baris-baris ini sudah lama punya tempat — sudah di mesin
pengering, sudah di silo, bahkan sudah digiling. Yang belum selesai bukan
gabahnya melainkan keputusannya: harganya belum diverifikasi, mutunya belum
diperiksa, outputnya belum dicocokkan.

Menaruhnya di antrean membuat orang mencari gabah yang sebenarnya sudah
ditempatkan — dan layar yang memerintahkan pencarian sia-sia akan berhenti
dipercaya, termasuk saat ia benar.

Hanya admin ke atas. Sejak awal ini memang pekerjaan admin; operator tak
pernah melihatnya, dan admin yang sedang memakai Mode operator pun tidak —
peran efektifnyalah yang ditanya, bukan peran aslinya.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import berjalan as svc
from app.web.security import butuh_admin
from app.web.tampilan import render

router = APIRouter(tags=["webapp"])


@router.get("/keputusan")
async def halaman_keputusan(request: Request, akun=Depends(butuh_admin)):
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)
    return render(
        request, "keputusan.html", layar="keputusan",
        meja=b.meja, lama=svc._lama,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        MENUNGGU=b.jumlah_menunggu, BERJALAN=b.jumlah_berjalan,
        KEPUTUSAN=b.jumlah_keputusan,
    )
