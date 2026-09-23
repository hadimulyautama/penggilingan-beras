"""Layar Stok — PK yang masih ada, dan gudangnya mengikuti VIEW pembacanya.

Satu alamat, dua isi. Operator selepan melihat lot giling Gudang 1; operator
polesan melihat silo dan tumpukan Gudang 2; Admin ke atas melihat keduanya,
Gudang 1 lebih dulu. Sebelum ini semua orang melihat Gudang 1 — termasuk
operator yang bekerja di Gudang 2, yang halaman Stoknya seluruhnya berisi
barang gudang sebelah.

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


async def _karung(db, view: str) -> list[dict]:
    """Baris stok karung yang boleh dilihat view ini — atau daftar kosong.

    Operator Gudang 1 tidak melihat blok ini sama sekali: karung mengemas
    beras JADI, dan itu pekerjaan Gudang 2. Yang memegang kedua gudang
    (Admin ke atas) ikut melihat karung PK di Gudang 1, karena ia yang
    memesannya.
    """
    from app.web.layar import gudang1, gudang2

    if not gudang2(view):
        return []
    from app.penggilingan.inventory import packaging as kms

    return [b for b in await kms.stok_kemasan_rinci(db)
            if b["gudang"] != "Gudang 1" or gudang1(view)]


@router.get("/stok")
async def halaman_stok(request: Request, akun=Depends(butuh_akun)):
    from app.services.setelan import fitur_mutu

    from app.web.layar import POLESAN, gudang1, gudang2

    view = getattr(request.state, "view", "tamu")
    async with SessionLocal() as db:
        # Gudang 1 per LOT GILING, Gudang 2 per TEMPAT — dua satuan, karena
        # bendanya memang dua rupa (lihat catatan di `app.services.stok`).
        # Operator hanya menerima gudangnya sendiri: halaman Stok yang
        # menampilkan silo gudang sebelah menjawab pertanyaan yang tak ia
        # ajukan, dan menenggelamkan yang ia ajukan.
        lot = await svc.pk_gudang1(db) if gudang1(view) else []
        tempat = await svc.pk_gudang2(db) if gudang2(view) else []
        mutu_aktif = await fitur_mutu(db)
        karung = await _karung(db, view)
    return await render_laci(
        request, "stok.html", layar="stok",
        lot=lot, tempat=tempat,
        total=sum(l.tersedia for l in lot),
        # `is_admin` sudah memakai peran EFEKTIF: saat admin memakai "Lihat
        # sebagai operator", `akun.user.role` diganti, jadi tombolnya ikut
        # hilang — samaran yang masih memegang wewenangnya bukan samaran.
        # Penjagaan sungguhannya tetap di rute aksinya sendiri; ini hanya
        # menyembunyikan tombol yang memang tak akan berhasil ditekan.
        # Koreksi hasil giling milik Gudang 1. Operator polesan tak punya
        # hasil giling untuk dikoreksi, dan tombolnya pun tak ada di
        # kartunya — tetapi `boleh_ubah` juga yang memasang `aksi.js` di
        # kaki halaman, jadi ia dimatikan di view yang tak memuat kartunya.
        boleh_ubah=akun.is_admin and view != POLESAN,
        # Stok karung, keputusan pemilik 23 September 2026: dilihat operator
        # Gudang 2, Admin, dan Super Admin — TIDAK operator Gudang 1. Aturan
        # siapa-melihat-apa tidak ditulis ulang di sini; ia sudah bernama
        # `gudang2(view)`, dan karung memang barang Gudang 2 (kecuali karung
        # PK, yang ikut ke sana hanya bagi yang juga memegang Gudang 1).
        karung=karung,
        # Mutu bisa dimatikan seluruhnya di Pengaturan — termasuk barisnya di
        # kartu ini. Setengah mati adalah yang terburuk: kartu yang masih
        # menyebut "belum dinilai" sementara borangnya tak ada menagih
        # pekerjaan yang tak bisa dikerjakan siapa pun.
        mutu_aktif=mutu_aktif,
        # Lembarnya terbuka DI SINI, bukan melemparkan orang ke layar aksi:
        # yang sedang dibaca adalah kartu ini, dan berpindah layar berarti
        # kehilangan tempatnya.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )
