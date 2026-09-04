"""Halaman Pengaturan — satu tempat untuk hal yang jarang diubah.

Dipisahkan dari beranda dengan sengaja. Beranda dipakai puluhan kali sehari
dan isinya keadaan pabrik; pengaturan dibuka beberapa kali setahun. Menaruh
keduanya berdampingan membuat yang sering dipakai harus melewati yang jarang.

Tiga bagian, dan urutannya mengikuti seberapa sering dipakai:
  · **Akun saya** — nama & kata sandi, milik siapa pun yang sedang masuk;
  · **Pengguna** — Direksi saja;
  · **Alat** — dryer & silo, Direksi saja.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from app.database import SessionLocal
from app.models import ProduksiAkun
from app.web.security import butuh_akun
from app.web.tampilan import redirect, render
from hmu_core import User

router = APIRouter(tags=["webapp"])


@router.get("/pengaturan")
async def halaman_pengaturan(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    from app.web.nav import jumlah_menunggu

    return render(
        request, "pengaturan.html", kembali="/",
        MENUNGGU=await jumlah_menunggu(akun.user),
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
    )


#: Hanya kunci yang dikenal yang jadi pesan — teks bebas dari URL tak pernah
#: ditampilkan, supaya halaman ini tak bisa dipakai menitipkan kalimat palsu
#: lewat tautan.
_PESAN = {
    "nama-diganti": "Nama Anda sudah diperbarui.",
    "sandi-diganti": "Kata sandi berhasil diganti.",
}


@router.post("/pengaturan/nama")
async def ganti_nama(
    request: Request,
    nama: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_akun),
):
    """Ganti nama sendiri — yang tampil di seluruh catatan.

    Namanya BUKAN sekadar label layar: ia menempel pada ribuan catatan lama
    lewat `created_by`, dan yang berubah di sini ikut berubah di semua catatan
    itu. Itu memang yang diinginkan — orangnya sama, ejaannya yang salah — dan
    justru karena itu tak boleh sembarang dikosongkan atau disingkat jadi satu
    huruf, sebab daftar akun lalu mustahil dibaca.
    """
    nama = " ".join(nama.split())
    if len(nama) < 3:
        return redirect("/pengaturan?err=nama-pendek")
    async with SessionLocal() as db:
        orang = await db.get(User, akun.user_id)
        if orang is None:
            return redirect("/pengaturan")
        orang.nama = nama
        await db.commit()
    return redirect("/pengaturan?pesan=nama-diganti")
