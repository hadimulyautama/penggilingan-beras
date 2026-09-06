"""Melihat aplikasi sebagai peran lain — untuk menguji, bukan untuk berkuasa.

Super Admin melihat GABUNGAN semua peran: layar Catat menampilkan aksi
operator Gudang 1, Gudang 2, dan staff sekaligus — puluhan tombol dalam satu
daftar datar. Itu membingungkan, dan lebih buruk lagi: ia membuat pemilik
tidak pernah melihat layar yang sesungguhnya dilihat operatornya.

Yang diubah CUKUP SATU TITIK: peran pada objek pengguna di memori. Objek itu
sudah lepas dari sesi basis data saat dikembalikan `akun_opsional`, jadi
perubahannya tak mungkin ikut tersimpan. Dan karena seluruh keputusan
tampilan — tab, daftar aksi, laporan, pengaturan — bertanya pada peran yang
sama, semuanya ikut tanpa satu pun disentuh.

**Hanya bisa MENURUN.** Peran yang diminta dibandingkan dengan peran asli;
yang lebih tinggi diabaikan. Karena itu kukinya tak perlu ditandatangani:
mengutak-atiknya paling jauh hanya membuat diri sendiri lebih tak berdaya.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.web.security import butuh_akun

router = APIRouter()

NAMA_KUKI = "produksi_lihat"

#: Tinggi tiap peran. `staff` peran lama yang masih dipakai akun lama.
TINGKAT = {"operator": 1, "staff": 2, "admin": 3, "superadmin": 4}

#: Yang boleh dipilih di layar, dari tertinggi.
PILIHAN = (
    ("", "Peran saya sendiri"),
    ("admin", "Admin"),
    ("operator", "Operator"),
)

NAMA_PERAN = {"operator": "Operator", "staff": "Staff",
              "admin": "Admin", "superadmin": "Super Admin"}


def peran_efektif(asli: str | None, diminta: str | None) -> str:
    """Peran yang dipakai tampilan — tak pernah lebih tinggi dari yang asli."""
    a = (asli or "").strip().lower()
    d = (diminta or "").strip().lower()
    if not d or d not in TINGKAT:
        return a
    if TINGKAT[d] > TINGKAT.get(a, 0):
        return a
    return d


def boleh_menyamar(asli: str | None) -> bool:
    """Admin ke atas. Operator tak punya peran di bawahnya untuk dicoba."""
    return TINGKAT.get((asli or "").strip().lower(), 0) >= TINGKAT["admin"]


@router.post("/lihat-sebagai")
async def pilih(request: Request, peran: str = Form(""), _=Depends(butuh_akun)):
    # `butuh_akun` WAJIB ada, bukan hiasan: ia yang memuat akun dan mengisi
    # `request.state.peran_asli`. Tanpanya peran asli selalu None, izinnya
    # selalu gagal, dan kukinya tak pernah terpasang — persis yang terjadi
    # pada percobaan pertama, tanpa satu pun galat muncul.
    asli = getattr(request.state, "peran_asli", None)
    balasan = RedirectResponse("/", status_code=303)
    if not boleh_menyamar(asli):
        return balasan
    pilih_ = peran_efektif(asli, peran)
    if not peran or pilih_ == (asli or "").strip().lower():
        balasan.delete_cookie(NAMA_KUKI, path="/")
    else:
        # Kuki sesi (tanpa umur): menyamar itu keadaan sementara untuk
        # menguji, bukan pengaturan yang menempel berhari-hari.
        balasan.set_cookie(NAMA_KUKI, pilih_, path="/", httponly=True,
                           samesite="lax")
    return balasan


@router.post("/lihat-sebagai/selesai")
async def selesai(request: Request, _=Depends(butuh_akun)):
    """Kembali ke peran sendiri.

    Sengaja TANPA syarat peran: yang sedang menyamar sebagai operator tak lagi
    punya hak admin, dan jalan pulang yang menuntut hak yang baru saja
    dilepas adalah pintu yang terkunci dari dalam.
    """
    balasan = RedirectResponse(request.headers.get("referer") or "/",
                               status_code=303)
    balasan.delete_cookie(NAMA_KUKI, path="/")
    return balasan
