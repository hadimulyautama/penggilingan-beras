"""Layar "Berjalan": pekerjaan yang belum tertutup, dan bisa ditutup dari sini.

Isinya disusun `app.services.berjalan`. Yang dikerjakan di sini hanya
menyajikannya — dan satu hal yang membuatnya berbeda dari laporan: tiap baris
menaut ke aksi yang MENUTUPnya, jadi menekan baris membuka formulir yang
benar dalam satu ketukan. Laporan memberi tahu; layar ini menyelesaikan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.database import SessionLocal
from app.services import berjalan as svc
from app.web.layar import GUDANG, MEJA
from app.web.security import butuh_akun
from app.web.tampilan import render, render_laci
from app.services import proses_aktif

router = APIRouter(tags=["webapp"])


async def _alih_proses(request, tujuan):
    # Penyegaran sesudah simpan memakai fetch. PINDAH sengaja mengabaikan
    # respons yang dialihkan, jadi 303 saja meninggalkan tindakan proses lama
    # di layar. Respons HTML ini dipasang seperti halaman biasa lalu membuka
    # fase/riwayat terbaru; kunjungan langsung tetap memakai 303.
    if request.headers.get("X-Pindah") == "1":
        return await render_laci(request, "proses_aktif_beralih.html",
                                 tujuan=tujuan, layar="berjalan")
    return RedirectResponse(tujuan, status_code=303)


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
        alamat_detail_proses=proses_aktif.alamat_detail,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        **b.lencana(),
        lama=svc._lama,
    )


@router.get("/proses-aktif/{jenis}/{kode}")
async def detail_proses_aktif(jenis: str, kode: str, request: Request,
                             akun=Depends(butuh_akun)):
    from app.models import DryingLot, MillingProcess
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.web.api import _is_g1_operator, _is_g2_operator

    if jenis not in proses_aktif.JENIS:
        raise HTTPException(404, "Jenis proses tidak ditemukan.")
    boleh = await (_is_g2_operator(akun.user) if jenis == "sosoh" else _is_g1_operator(akun.user))
    if not boleh:
        raise HTTPException(403, "Proses ini berada di gudang lain. Pilih gudang kerja yang sesuai.")
    model, kolom = ((PolishingProcess, PolishingProcess.kode_proses) if jenis == "sosoh"
                    else (MillingProcess, MillingProcess.kode_proses) if jenis == "giling"
                    else (DryingLot, DryingLot.kode_lot))
    async with SessionLocal() as db:
        p = await db.scalar(select(model).where(kolom == kode))
        if p is None:
            raise HTTPException(404, "Proses tidak ditemukan.")
        if jenis in ("pengeringan", "pendinginan"):
            if p.waktu_selesai_pendinginan is not None:
                return await _alih_proses(request, f"/riwayat-pengeringan/{p.id}")
            fase_kini = "pengeringan" if p.status == "proses" else "pendinginan" if p.status == "selesai" else None
            if fase_kini and jenis != fase_kini:
                return await _alih_proses(request, f"/proses-aktif/{fase_kini}/{kode}")
        elif p.status == "selesai":
            return await _alih_proses(request, f"/riwayat-{'sosoh' if jenis == 'sosoh' else 'giling'}/{p.id}")
        elif p.status != "proses":
            raise HTTPException(404, "Proses ini sudah tidak aktif.")

        if jenis == "sosoh":
            daftar = await svc._kartu_penyosohan_g2(db, None, kode_proses=kode, lengkap=True)
        else:
            # Kartu yang sama dengan daftar, termasuk gerbang QC untuk operator.
            b = await svc.untuk(db, akun.user)
            daftar = b.berjalan
        kartu = next((x for x in daftar if x.kode == kode and
                      (x.fase == "sosoh" if jenis == "sosoh" else
                       x.fase == "giling" if jenis == "giling" else x.fase == "dryer")), None)
        if kartu is None:
            raise HTTPException(404, "Proses ini sudah tidak aktif.")
        from app.services.identitas_pekerjaan import lengkapi
        await lengkapi(db, [kartu])
        detail = await proses_aktif.rincian(db, jenis=jenis, model=p, kartu=kartu,
                                           params=request.query_params)
    dasar = request.url.remove_query_params(["buka", "nilai"])
    def halaman(parameter, nomor):
        return str(dasar.include_query_params(**{parameter: nomor}))
    return await render_laci(
        request, "proses_aktif_detail.html", d=detail, proses=kartu,
        layar="berjalan", breadcrumb_detail=kode, kembali="/berjalan",
        alamat=request.url.path, halaman_proses=halaman,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )
