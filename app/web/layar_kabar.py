"""Layar Kabar — pembaca `notifications`, yang selama ini tak ada.

Keputusan pemilik 26 September 2026. Sebabnya dan seluruh pertimbangannya ada
di `services.kabar`; yang di sini cuma rutenya.

DIBUKA = DIBACA. Membuka layar ini menandai yang tergambar sebagai `dibaca`,
jadi lencananya bisa kembali nol tanpa satu ketukan tambahan. Tombol "tandai
sudah dibaca" sengaja TIDAK ada: ia ketukan kedua untuk pekerjaan yang sudah
selesai saat matanya sampai ke baris itu, dan daftar yang harus dipencet supaya
bersih akan berhenti dibuka orang yang bekerja dengan satu tangan.

Yang tetap menagih pekerjaan bukan layar ini melainkan kartunya di Antrian
tunggu dan Menunggu keputusan. Kabar yang sudah dibaca TETAP tergambar sampai
umurnya habis — ia riwayat tujuh hari, bukan kotak masuk yang harus dikosongkan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import kabar as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/kabar")
async def halaman_kabar(request: Request, akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        baris = await svc.daftar(db, akun.user)
        # Angka lencana diambil SEBELUM menandai terbaca: laci di halaman ini
        # harus menyebut jumlah yang sama dengan jumlah baris bertanda "baru"
        # yang sedang dibaca orangnya. Kalau ditandai lebih dulu, lencananya nol
        # sementara di bawahnya tiga baris masih bertanda baru — dan yang
        # dibaca orang bukan "sudah saya tandai" melainkan "lencananya bohong".
        baru = sum(1 for k in baris if k.baru)
        await svc.tandai_terbaca(db, [k.id for k in baris if k.baru])
    return await render_laci(request, "kabar.html", layar="kabar",
                             kabar=baris, baru=baru, hari=svc.HARI,
                             # Lencana di laci halaman ini sudah nol — kabarnya
                             # baru saja terbaca. `render_laci` menghitungnya
                             # ulang sesudah penandaan, jadi angkanya benar
                             # dengan sendirinya; yang perlu disebut halaman ini
                             # berapa yang BARU SAJA dibacakan kepadanya.
                             )
