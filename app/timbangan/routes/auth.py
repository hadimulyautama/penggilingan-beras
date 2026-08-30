"""Rute masuk & keluar.

Sesi bertahan sampai petugas menekan Keluar. Tiap orang memakai perangkatnya
sendiri, jadi membuka aplikasi lagi tidak boleh meminta sandi — di pos timbang,
truk tidak menunggu orang mengetik kata sandi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
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
from app.timbangan.web import BASE_DIR, PREFIX, redirect, render

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

    # Kode perangkat TIDAK lagi diisi di sini. Dulu layar masuk memintanya,
    # dan siapa pun yang mengetik kode perangkat orang lain diam-diam
    # memindahkan deret nomor transaksi ke dirinya — dua perangkat tanpa
    # jaringan lalu bisa membuat nomor yang sama, persis yang hendak dicegah.
    # Sekarang kodenya melekat pada akun dan hanya Admin yang menetapkannya.
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


@router.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Service worker, dilayani dari akar modul — bukan dari /static/.

    Peramban menolak service worker yang mengaku menaungi cakupan di ATAS
    letaknya sendiri. Disajikan dari `/static/sw.js`, pendaftaran untuk
    cakupan `/timbangan/` selalu gagal — diam-diam, hanya sebagai galat di
    konsol — sehingga halaman cadangan luring tidak pernah benar-benar
    aktif. Di pos timbang yang sinyalnya naik-turun, itu justru bagian yang
    paling dibutuhkan.

    Header `Service-Worker-Allowed` dipertahankan sebagai sabuk pengaman
    kedua bila suatu saat berkasnya dipindah lagi.
    """
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": f"{PREFIX}/",
            # Jangan di-cache: inilah berkas yang memutuskan versi cache
            # lainnya. Kalau ia sendiri basi, pembaruan tidak pernah sampai.
            "Cache-Control": "no-cache",
        },
    )
