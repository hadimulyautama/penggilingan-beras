"""Rute masuk, keluar, dan ganti sandi webapp produksi.

Dua jenis perangkat, dua perlakuan sesi (lihat `ProduksiAkun.mode_perangkat`):

- **Operator — perangkat gudang.** Sesi pendek dan diperpanjang tiap kali
  dipakai, jadi ia mati sendiri setelah ditinggal menganggur. Tanpa itu,
  orang berikutnya yang memegang perangkat akan mencatat pekerjaannya atas
  nama orang sebelumnya, dan jejak auditnya tetap rapi tapi isinya salah.
- **Admin & staff — perangkat sendiri.** Sesi panjang; membuka aplikasi lagi
  tidak meminta sandi.

Karena perangkat gudang berarti login berkali-kali dalam sehari, halaman masuk
mengingat siapa saja yang pernah memakai perangkat itu dan menawarkannya
sebagai tombol: pilih nama, ketik sandi. Yang disimpan hanya nama pengguna —
tidak ada token, tidak ada sandi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select

from app.database import SessionLocal, now_local
from app.models import ProduksiAkun
from app.web.security import (
    COOKIE_PERANGKAT,
    NAMA_COOKIE,
    akun_opsional,
    baca_nama_perangkat,
    buat_token,
    butuh_akun,
    cek_sandi,
    hash_sandi,
    tulis_nama_perangkat,
    umur_sesi_detik,
)
from app.web.tampilan import redirect, render

router = APIRouter(tags=["webapp"])

_SETAHUN = 365 * 24 * 3600


def _bersihkan_nama(v: str | None) -> str:
    """Nama pengguna dari URL — disaring ketat sebelum masuk ke halaman."""
    nama = (v or "").strip().lower()
    if not nama or len(nama) > 50 or not nama.isascii():
        return ""
    return nama if nama.replace("_", "").replace("-", "").isalnum() else ""


@router.get("/masuk")
async def halaman_masuk(request: Request):
    akun = await akun_opsional(request)
    if akun is not None:
        return redirect("/")
    pilih = _bersihkan_nama(request.query_params.get("u"))
    riwayat = baca_nama_perangkat(request.cookies.get(COOKIE_PERANGKAT))
    return render(
        request, "masuk.html",
        tujuan=request.query_params.get("next", ""),
        username=pilih,
        riwayat=[n for n in riwayat if n != pilih],
    )


@router.post("/masuk")
async def proses_masuk(
    request: Request,
    username: str = Form(...),
    sandi: str = Form(...),
    tujuan: str = Form(""),
):
    uname = username.strip().lower()
    riwayat = baca_nama_perangkat(request.cookies.get(COOKIE_PERANGKAT))

    def gagal(pesan: str):
        # Nama pengguna dikembalikan ke formulir. Mengosongkannya berarti
        # mengetik ulang hanya karena salah satu huruf sandi — hukuman untuk
        # kesalahan yang bukan di situ.
        return render(request, "masuk.html", tujuan=tujuan, username=uname,
                      riwayat=[n for n in riwayat if n != uname], pesan_err=pesan)

    async with SessionLocal() as db:
        akun = (await db.execute(
            select(ProduksiAkun).where(ProduksiAkun.username == uname)
        )).scalars().first()

        # Pesan yang sama untuk pengguna tak dikenal maupun sandi salah —
        # jangan memberi tahu penebak mana dari keduanya yang benar.
        if akun is None or not cek_sandi(sandi, akun.password_hash):
            return gagal("Nama pengguna atau kata sandi salah.")
        if akun.status != "aktif":
            return gagal("Akun ini sedang dinonaktifkan. Hubungi Super Admin.")

        akun.terakhir_login = now_local()
        wajib_ganti = akun.harus_ganti_sandi
        await db.commit()
        await db.refresh(akun)

    balasan = redirect("/ganti-sandi" if wajib_ganti else (tujuan or "/"))
    balasan.set_cookie(
        NAMA_COOKIE, buat_token(akun), max_age=umur_sesi_detik(akun),
        httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/",
    )
    balasan.set_cookie(
        COOKIE_PERANGKAT,
        tulis_nama_perangkat(request.cookies.get(COOKIE_PERANGKAT), uname),
        max_age=_SETAHUN, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )
    return balasan


@router.post("/keluar")
async def proses_keluar(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    """Keluar hanya membuang sesi. Daftar nama di perangkat sengaja DITAHAN —
    itulah yang membuat pemakai berikutnya cukup menekan namanya."""
    balasan = redirect(f"/masuk?u={akun.username}")
    balasan.delete_cookie(NAMA_COOKIE, path="/")
    return balasan


@router.get("/ganti-sandi")
async def halaman_ganti_sandi(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    return render(request, "ganti_sandi.html", wajib=akun.harus_ganti_sandi,
                  kembali=None if akun.harus_ganti_sandi else "/")


@router.post("/ganti-sandi")
async def proses_ganti_sandi(
    request: Request,
    sandi_baru: str = Form(...),
    ulangi: str = Form(...),
    sandi_lama: str = Form(""),
    akun: ProduksiAkun = Depends(butuh_akun),
):
    wajib = akun.harus_ganti_sandi

    def gagal(pesan: str):
        return render(request, "ganti_sandi.html", wajib=wajib,
                      kembali=None if wajib else "/", pesan_err=pesan)

    # Saat sandi masih sandi awal dari Super Admin, sandi lama TIDAK diminta:
    # orangnya baru saja membuktikan dirinya beberapa detik lalu di halaman
    # masuk, dan memintanya mengetik ulang sandi yang justru sedang dibuang
    # hanya menambah satu kesempatan salah ketik.
    if not wajib and not cek_sandi(sandi_lama, akun.password_hash):
        return gagal("Kata sandi lama salah.")
    if sandi_baru != ulangi:
        return gagal("Kata sandi baru dan ulangannya tidak sama.")
    if cek_sandi(sandi_baru, akun.password_hash):
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

    # Selesai berarti selesai: kembali ke beranda dengan kabar baiknya, bukan
    # tertinggal di formulir yang sudah tidak ada gunanya.
    return redirect("/?pesan=sandi-diganti")
