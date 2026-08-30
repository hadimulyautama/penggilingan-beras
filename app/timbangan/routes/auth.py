"""Rute masuk & keluar.

Sesi bertahan sampai petugas menekan Keluar. Tiap orang memakai perangkatnya
sendiri, jadi membuka aplikasi lagi tidak boleh meminta sandi — di pos timbang,
truk tidak menunggu orang mengetik kata sandi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import service
from app.timbangan.config import tsettings
from app.timbangan.db import get_db, sekarang
from app.timbangan.models import TimbanganAkun
from app.timbangan.security import (
    NAMA_COOKIE,
    akun_opsional,
    buat_token,
    butuh_akun,
    cek_sandi,
)
from app.timbangan.web import PREFIX, redirect, render

router = APIRouter(prefix=PREFIX)


@router.get("/masuk")
async def halaman_masuk(request: Request):
    akun = await akun_opsional(request)
    if akun is not None:
        return RedirectResponse(f"{PREFIX}/", status_code=303)
    return render(
        request, "masuk.html",
        tujuan=request.query_params.get("next", ""),
    )


@router.post("/masuk")
async def proses_masuk(
    request: Request,
    username: str = Form(...),
    sandi: str = Form(...),
    perangkat: str = Form(""),
    tujuan: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    akun = (await db.execute(
        select(TimbanganAkun).where(
            TimbanganAkun.username == username.strip().lower()
        )
    )).scalars().first()

    # Pesan yang sama untuk pengguna tidak dikenal maupun sandi salah — jangan
    # memberi tahu penebak mana dari keduanya yang benar.
    if akun is None or not cek_sandi(sandi, akun.password_hash):
        return render(
            request, "masuk.html", tujuan=tujuan,
            pesan_err="Nama pengguna atau kata sandi salah.",
        )
    if akun.status != "aktif":
        return render(
            request, "masuk.html", tujuan=tujuan,
            pesan_err="Akun ini sedang dinonaktifkan. Hubungi Admin.",
        )

    # Kode perangkat ikut menyusun nomor transaksi, jadi tiap perangkat harus
    # punya kode sendiri agar nomor tidak bentrok saat dibuat tanpa jaringan.
    kode_perangkat = (perangkat or "").strip().upper()[:8]
    if kode_perangkat:
        akun.perangkat_kode = kode_perangkat
    akun.terakhir_login = sekarang()

    await service.catat_audit(
        db, akun=akun, aksi="LOGIN", entitas="akun", entitas_id=akun.id,
        perangkat=akun.perangkat_kode,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    aman = request.url.scheme == "https"
    balasan = RedirectResponse(tujuan or f"{PREFIX}/", status_code=303)
    balasan.set_cookie(
        NAMA_COOKIE, buat_token(akun.id),
        max_age=tsettings.sesi_hari * 24 * 3600,
        httponly=True, samesite="lax", secure=aman, path=PREFIX,
    )
    return balasan


@router.get("/akun")
async def halaman_akun(akun: TimbanganAkun = Depends(butuh_akun)):
    """Tautan lama — isinya kini jadi satu dengan halaman Pengaturan."""
    return RedirectResponse(f"{PREFIX}/pengaturan", status_code=307)


@router.post("/keluar")
async def proses_keluar(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    await service.catat_audit(
        db, akun=akun, aksi="LOGOUT", entitas="akun", entitas_id=akun.id,
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    balasan = RedirectResponse(f"{PREFIX}/masuk", status_code=303)
    balasan.delete_cookie(NAMA_COOKIE, path=PREFIX)
    return balasan


@router.get("/luring")
async def halaman_luring(request: Request):
    """Halaman cadangan yang dilayani service worker saat jaringan hilang."""
    return render(request, "luring.html")
