"""Rute masuk, keluar, dan ganti sandi webapp produksi.

Dua jenis perangkat, dua perlakuan sesi (lihat `ProduksiAkun.mode_perangkat`):

- **Operator — perangkat gudang.** Sesi pendek dan diperpanjang tiap kali
  dipakai, jadi ia mati sendiri setelah ditinggal menganggur. Tanpa itu,
  orang berikutnya yang memegang perangkat akan mencatat pekerjaannya atas
  nama orang sebelumnya, dan jejak auditnya tetap rapi tapi isinya salah.
- **Admin & staff — perangkat sendiri.** Sesi panjang; membuka aplikasi lagi
  tidak meminta sandi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select

from app.database import SessionLocal, now_local
from app.models import ProduksiAkun
from app.web.security import (
    NAMA_COOKIE,
    akun_opsional,
    buat_token,
    butuh_akun,
    cek_sandi,
    hash_sandi,
    umur_sesi_detik,
)
from app.web.tampilan import redirect, render

router = APIRouter(tags=["webapp"])


def _pasang_cookie(request: Request, balasan, akun: ProduksiAkun):
    balasan.set_cookie(
        NAMA_COOKIE, buat_token(akun),
        max_age=umur_sesi_detik(akun),
        httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return balasan


@router.get("/masuk")
async def halaman_masuk(request: Request):
    akun = await akun_opsional(request)
    if akun is not None:
        return redirect("/")
    return render(request, "masuk.html", tujuan=request.query_params.get("next", ""))


@router.post("/masuk")
async def proses_masuk(
    request: Request,
    username: str = Form(...),
    sandi: str = Form(...),
    tujuan: str = Form(""),
):
    async with SessionLocal() as db:
        akun = (await db.execute(
            select(ProduksiAkun).where(
                ProduksiAkun.username == username.strip().lower()
            )
        )).scalars().first()

        # Pesan yang sama untuk pengguna tak dikenal maupun sandi salah —
        # jangan memberi tahu penebak mana dari keduanya yang benar.
        if akun is None or not cek_sandi(sandi, akun.password_hash):
            return render(request, "masuk.html", tujuan=tujuan,
                          pesan_err="Nama pengguna atau kata sandi salah.")
        if akun.status != "aktif":
            return render(request, "masuk.html", tujuan=tujuan,
                          pesan_err="Akun ini sedang dinonaktifkan. Hubungi Direksi.")

        akun.terakhir_login = now_local()
        wajib_ganti = akun.harus_ganti_sandi
        await db.commit()
        await db.refresh(akun)

    lanjut = "/ganti-sandi" if wajib_ganti else (tujuan or "/")
    return _pasang_cookie(request, redirect(lanjut), akun)


@router.post("/keluar")
async def proses_keluar(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    balasan = redirect("/masuk")
    balasan.delete_cookie(NAMA_COOKIE, path="/")
    return balasan


@router.get("/ganti-sandi")
async def halaman_ganti_sandi(
    request: Request, akun: ProduksiAkun = Depends(butuh_akun)
):
    return render(request, "ganti_sandi.html", wajib=akun.harus_ganti_sandi)


@router.post("/ganti-sandi")
async def proses_ganti_sandi(
    request: Request,
    sandi_lama: str = Form(...),
    sandi_baru: str = Form(...),
    ulangi: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_akun),
):
    def gagal(pesan: str):
        return render(request, "ganti_sandi.html",
                      wajib=akun.harus_ganti_sandi, pesan_err=pesan)

    if not cek_sandi(sandi_lama, akun.password_hash):
        return gagal("Kata sandi lama salah.")
    if sandi_baru != ulangi:
        return gagal("Kata sandi baru dan ulangannya tidak sama.")
    if sandi_baru == sandi_lama:
        return gagal("Kata sandi baru harus berbeda dari yang lama.")
    try:
        hash_baru = hash_sandi(sandi_baru)
    except ValueError as e:
        return gagal(str(e))

    async with SessionLocal() as db:
        baris = await db.get(ProduksiAkun, akun.id)
        baris.password_hash = hash_baru
        baris.harus_ganti_sandi = False
        await db.commit()

    return render(request, "ganti_sandi.html", wajib=False,
                  pesan_ok="Kata sandi berhasil diganti.")
