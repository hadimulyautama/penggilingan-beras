"""Kelola akun webapp — hanya Direksi.

Akun TIDAK pernah dihapus, hanya dinonaktifkan: `created_by` pada ribuan
catatan lama menunjuk ke `users.id`, dan orangnya harus tetap bisa dikenali
bertahun-tahun setelah ia berhenti.

Sandi awal dibuatkan sistem, dibacakan sekali kepada orangnya, dan wajib
diganti saat ia pertama masuk — sehingga Direksi tidak ikut memegang sandi
orang lain.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fastapi import APIRouter, Depends, Form, Request

from app.database import SessionLocal
from app.models import ProduksiAkun
from app.models.akun import mode_bawaan
from app.web.security import butuh_admin, hash_sandi, sandi_acak
from app.web.tampilan import render
from hmu_core import User

router = APIRouter(tags=["webapp"])

_MODE = ("pribadi", "bersama")


def _saran_username(nama: str) -> str:
    """Tebakan nama pengguna dari nama orang: kata pertama, huruf kecil.

    Direksi tetap boleh menggantinya. Gunanya menghapus satu keputusan kecil
    yang tak ada nilainya — dan mencegah kebun binatang nama pengguna yang
    formatnya berbeda-beda tergantung siapa yang sedang membuatkan akun.
    """
    kata = ["".join(c for c in k.lower() if c.isalnum()) for k in nama.split()]
    kata = [k for k in kata if k]
    # Lewati inisial: "M. Yusuf" harus jadi "yusuf", bukan "m".
    for k in kata:
        if len(k) >= 3:
            return k[:20]
    return "".join(kata)[:20]


async def _muat(pesan_ok: str | None = None, pesan_err: str | None = None,
                sandi_awal: dict | None = None) -> dict:
    """Daftar akun + orang di `users` yang belum punya akun."""
    async with SessionLocal() as db:
        akun_list = (await db.execute(
            select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
            .order_by(ProduksiAkun.username)
        )).scalars().all()
        sudah = {a.user_id for a in akun_list}
        belum = [
            u for u in (await db.execute(
                select(User).where(User.status == "aktif").order_by(User.nama)
            )).scalars().all()
            if u.id not in sudah
        ]
    return {"akun_list": akun_list, "kembali": "/",
            "belum": [{"id": u.id, "nama": u.nama, "role": u.role,
                       "saran": _saran_username(u.nama)} for u in belum],
            "pesan_ok": pesan_ok, "pesan_err": pesan_err, "sandi_awal": sandi_awal}


@router.get("/pengguna")
async def halaman_pengguna(request: Request, _=Depends(butuh_admin)):
    return render(request, "pengguna.html", **await _muat())


@router.post("/pengguna/buat")
async def buat_akun(
    request: Request,
    user_id: int = Form(...),
    username: str = Form(...),
    _=Depends(butuh_admin),
):
    uname = username.strip().lower()
    if not uname or " " in uname or len(uname) < 3:
        return render(request, "pengguna.html",
                      **await _muat(pesan_err="Nama pengguna minimal 3 huruf, tanpa spasi."))
    sandi = sandi_acak()
    async with SessionLocal() as db:
        orang = await db.get(User, user_id)
        if orang is None:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err="Orang itu tidak ada di daftar pengguna."))
        bentrok = (await db.execute(
            select(ProduksiAkun).where(ProduksiAkun.username == uname)
        )).scalars().first()
        if bentrok is not None:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err=f"Nama pengguna '{uname}' sudah dipakai."))
        db.add(ProduksiAkun(
            user_id=orang.id, username=uname, password_hash=hash_sandi(sandi),
            mode_perangkat=mode_bawaan(orang.role), harus_ganti_sandi=True,
        ))
        await db.commit()
        nama = orang.nama
    # Sandi awal ditampilkan sebagai blok tersendiri, bukan diselipkan dalam
    # kalimat: ini satu-satunya kesempatan membacanya, dan yang membacanya
    # sedang berdiri di depan orangnya.
    return render(request, "pengguna.html", **await _muat(
        sandi_awal={"nama": nama, "username": uname, "sandi": sandi,
                    "judul": "Akun dibuat"}))


@router.post("/pengguna/reset")
async def reset_sandi(request: Request, akun_id: int = Form(...), _=Depends(butuh_admin)):
    sandi = sandi_acak()
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        akun.password_hash = hash_sandi(sandi)
        akun.harus_ganti_sandi = True
        uname, nama = akun.username, akun.nama
        await db.commit()
    return render(request, "pengguna.html", **await _muat(
        sandi_awal={"nama": nama, "username": uname, "sandi": sandi,
                    "judul": "Sandi disetel ulang"}))


@router.post("/pengguna/status")
async def ubah_status(request: Request, akun_id: int = Form(...), _=Depends(butuh_admin)):
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        akun.status = "nonaktif" if akun.status == "aktif" else "aktif"
        pesan = f"Akun '{akun.username}' sekarang {akun.status}."
        await db.commit()
    return render(request, "pengguna.html", **await _muat(pesan_ok=pesan))


@router.post("/pengguna/mode")
async def ubah_mode(
    request: Request, akun_id: int = Form(...), mode: str = Form(...),
    _=Depends(butuh_admin),
):
    if mode not in _MODE:
        return render(request, "pengguna.html", **await _muat(pesan_err="Jenis perangkat tidak dikenal."))
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        akun.mode_perangkat = mode
        pesan = (f"Perangkat '{akun.username}' disetel ke "
                 f"{'milik gudang (sesi pendek)' if mode == 'bersama' else 'milik sendiri (sesi panjang)'}.")
        await db.commit()
    return render(request, "pengguna.html", **await _muat(pesan_ok=pesan))
