"""Layar Stok — PK Gudang 1 yang masih ada, per lot giling.

Operator hanya membaca. Yang boleh mengoreksi hanya Admin ke atas, dan yang
dikoreksi adalah HASIL GILINGNYA — bukan angka stoknya.

Bedanya penting. Stok = hasil − dikirim − dijual; membolehkan orang mengetik
stok berarti membolehkan salah satu dari ketiganya dibengkokkan tanpa jejak,
dan selisih yang ditutupi berhenti jadi pertanyaan. Yang dibuka di sini justru
aksi yang sudah ada dan sudah tercatat: verifikasi output giling. Ia menulis
`berat_output_final_kg`, masuk log aktivitas, bisa dibatalkan lewat List audit,
dan karena rendemen serta stok adalah TURUNAN dari angka itu, keduanya berubah
sendiri — tak ada angka kedua yang bisa berselisih.
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
        # `is_admin` sudah memakai peran EFEKTIF: saat admin memakai "Lihat
        # sebagai operator", `akun.user.role` diganti, jadi tombolnya ikut
        # hilang — samaran yang masih memegang wewenangnya bukan samaran.
        # Penjagaan sungguhannya tetap di rute aksinya sendiri; ini hanya
        # menyembunyikan tombol yang memang tak akan berhasil ditekan.
        boleh_ubah=akun.is_admin,
        # Lembarnya terbuka DI SINI, bukan melemparkan orang ke layar aksi:
        # yang sedang dibaca adalah kartu ini, dan berpindah layar berarti
        # kehilangan tempatnya.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )
