"""Tiga layar "Riwayat Proses" Gudang 1 — Penggilingan, Pengeringan, Transfer.

Sub-menu "Riwayat Proses" (`app/web/nav.py`, kunci `riwayat_sosoh` — ia
sekaligus pintu induk dropdown ini dan pintu "Penyosohan" sendiri, lihat
catatan di sana). Ketiganya di sini satu berkas, pola sama `layar_produk.py`
menampung `/stok-produk` *dan* `/stok-produk-jasa`: tiga layar yang berdiri
sendiri tetapi berbagi gerbang (`_is_g1_operator`) dan bentuk kursor
(`?sebelum=<id>`, pola sama `layar_sosoh.py`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()

#: Sekali muat — sama `layar_sosoh.SEKALI`, alasan yang sama: cukup besar
#: untuk sebulan pekerjaan, cukup kecil untuk dibuka di gudang lewat 4G.
SEKALI = 30


def _sebelum_id(request: Request) -> int | None:
    """`?sebelum=` → id kursor, atau None. Ngawur diperlakukan "dari awal",
    bukan galat — alamat ini sering diketik/ditempel, dan 422 di sini tak
    memberi jalan keluar kepada yang membacanya. Sama persis `layar_sosoh`.
    """
    sebelum = request.query_params.get("sebelum")
    try:
        return int(sebelum) if sebelum else None
    except ValueError:
        return None


@router.get("/riwayat-giling")
async def halaman_riwayat_giling(request: Request, akun=Depends(butuh_akun)):
    """Kartu giling selesai, terbaru lebih dulu, berikut PK yang jadi."""
    from app.web.api import _is_g1_operator

    # ⚠ DIJAGA DI RUTENYA, bukan cuma di daftar pintu — alamatnya tetap bisa
    # diketik, sama alasan yang menjaga `/riwayat-sosoh`.
    if not await _is_g1_operator(akun.user):
        raise HTTPException(
            403, "Riwayat Penggilingan milik Admin ke atas dan operator Gudang 1.")

    from app.penggilingan.gudang1.services.milling import riwayat_giling

    sebelum_id = _sebelum_id(request)
    async with SessionLocal() as db:
        kartu, lagi = await riwayat_giling(db, batas=SEKALI, sebelum=sebelum_id)
    return await render_laci(
        request, "riwayat_giling.html",
        kartu=kartu, lagi=lagi, SEKALI=SEKALI,
        sesudah=(kartu[-1].id if kartu and lagi else None),
        dari_awal=bool(sebelum_id),
    )


@router.get("/riwayat-pengeringan")
async def halaman_riwayat_pengeringan(request: Request, akun=Depends(butuh_akun)):
    """Kartu lot pengeringan selesai (kering+dingin), terbaru lebih dulu."""
    from app.web.api import _is_g1_operator

    if not await _is_g1_operator(akun.user):
        raise HTTPException(
            403, "Riwayat Pengeringan milik Admin ke atas dan operator Gudang 1.")

    from app.penggilingan.gudang1.services.drying import riwayat_pengeringan

    sebelum_id = _sebelum_id(request)
    async with SessionLocal() as db:
        kartu, lagi = await riwayat_pengeringan(db, batas=SEKALI, sebelum=sebelum_id)
    return await render_laci(
        request, "riwayat_pengeringan.html",
        kartu=kartu, lagi=lagi, SEKALI=SEKALI,
        sesudah=(kartu[-1].id if kartu and lagi else None),
        dari_awal=bool(sebelum_id),
    )


@router.get("/riwayat-transfer")
async def halaman_riwayat_transfer(request: Request, akun=Depends(butuh_akun)):
    """Kartu transfer PK Gudang 1 → Gudang 2, dibatalkan atau tidak."""
    from app.web.api import _is_g1_operator

    if not await _is_g1_operator(akun.user):
        raise HTTPException(
            403, "Riwayat Transfer milik Admin ke atas dan operator Gudang 1.")

    from app.services.transfer import riwayat_transfer

    sebelum_id = _sebelum_id(request)
    async with SessionLocal() as db:
        kartu, lagi = await riwayat_transfer(db, batas=SEKALI, sebelum=sebelum_id)
    return await render_laci(
        request, "riwayat_transfer.html",
        kartu=kartu, lagi=lagi, SEKALI=SEKALI,
        sesudah=(kartu[-1].id if kartu and lagi else None),
        dari_awal=bool(sebelum_id),
    )
