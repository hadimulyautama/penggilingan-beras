"""Layar Stok Produk — HASIL pabrik, bukan bahannya.

Keputusan pemilik 26 September 2026: "bagusnya ada halaman baru yaitu Stok
Produk, dan kartu hasil sosoh berada di situ."

Sebabnya temuan QA hari itu: beras yang sudah keluar dari mesin sosoh tidak ada
di angka stok mana pun. `polishing_output_logs` dibaca tepat dua tempat di
seluruh repo — pembanding internal, dan satu baris ringkasan laporan — dan tak
satu pun layar stok membacanya. Beras baru MENJADI stok ketika seseorang
menjalankan "Catat packing"; di pabrik, jarak antara "sosoh selesai" dan
"packing dicatat" adalah jam, kadang hari. Sepanjang waktu itu berton-ton beras
berdiri di lantai sementara aplikasi menyebut stoknya nol.

Ketimpangannya dengan Gudang 1 yang membuatnya terasa hilang: lot giling yang
selesai berkartu lengkap di layar Stok, dan PK-nya terhitung siap kirim. Output
Gudang 1 adalah stok; output Gudang 2 tinggal baris log — padahal keduanya
sama-sama barang yang berdiri di lantai gudang.

PEMBAGIANNYA:
    /stok         BAHAN  — gabah di silo Gudang 1, PK di Gudang 2
    /stok-produk  HASIL  — beras (curah & dikemas) dan hasil samping

Tiga blok, urutannya mengikuti umur barangnya: yang baru keluar mesin lebih
dulu, yang sudah dikemas berikutnya, hasil samping menyusul.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.services import stok as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/stok-produk")
async def halaman_stok_produk(request: Request, akun=Depends(butuh_akun)):
    from app.web.layar import SELEPAN

    view = getattr(request.state, "view", "tamu")
    # Operator selepan tak punya urusan di sini — beras dan hasil samping lahir
    # di Gudang 2. Pintunya sudah tak ditawarkan (`PINTU_MATI`), tetapi pintu
    # yang disembunyikan bukan penjagaan: alamatnya bisa diketik, dan lembar
    # yang masih terbuka di layar orang lain masih bisa memanggilnya.
    if view == SELEPAN:
        raise HTTPException(403, "Layar ini milik Gudang 2.")
    async with SessionLocal() as db:
        curah = await svc.beras_curah(db)
        bj = await svc.barang_jadi_g2(db)
    return await render_laci(
        request, "stok_produk.html", layar="stok_produk",
        curah=curah,
        produk=bj.produk, samping=bj.samping,
        total_curah=sum(c.sisa_kg for c in curah if c.sisa_kg > 0),
    )
