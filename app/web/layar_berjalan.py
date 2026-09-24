"""Layar "Berjalan": pekerjaan yang belum tertutup, dan bisa ditutup dari sini.

Isinya disusun `app.services.berjalan`. Yang dikerjakan di sini hanya
menyajikannya — dan satu hal yang membuatnya berbeda dari laporan: tiap baris
menaut ke aksi yang MENUTUPnya, jadi menekan baris membuka formulir yang
benar dalam satu ketukan. Laporan memberi tahu; layar ini menyelesaikan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import berjalan as svc
from app.web.layar import GUDANG, MEJA
from app.web.security import butuh_akun
from app.web.tampilan import render

router = APIRouter(tags=["webapp"])


@router.get("/berjalan")
async def halaman_berjalan(request: Request, akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)

    # ── Penyaring gudang (celah ke-4 menjelang app meja dihapus) ──
    #
    # Hanya untuk view yang memegang KEDUA gudang. Operator sudah diberi satu
    # gudang lewat view-nya, jadi daftarnya kosong dan templat tak menggambar
    # apa pun — pil tunggal bernama "Semua" tak membedakan apa pun.
    #
    # Daftarnya dari master gudang (`layar.GUDANG`), bukan dua pil tetap:
    # menambah gudang berarti menambah baris di master. Dan penyaringnya
    # membaca `b.gudang` yang dicap penyusunnya sendiri — bukan menebak dari
    # kode kartunya.
    view = getattr(request.state, "view", "tamu")
    saring = GUDANG if view in MEJA else ()
    gudang = request.query_params.get("gudang") or ""
    if gudang not in {g for g, _, _ in saring}:
        gudang = ""                       # nilai karangan dari URL diabaikan
    pilih = (lambda xs: [x for x in xs if not gudang or x.gudang == gudang])

    return render(
        request, "berjalan.html",
        SARING_GUDANG=saring, gudang=gudang,
        # Mesin yang menyala, dan gabah yang sudah punya tempat tetapi tak
        # sedang diapa-apakan. Antrean tak ikut ke sini — ia punya layarnya
        # sendiri.
        berjalan=pilih(b.berjalan), transit=pilih(b.transit),
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        **b.lencana(),
        lama=svc._lama,
    )
