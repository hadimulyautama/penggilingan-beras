"""Layar "List audit": siapa mencatat apa, jam berapa.

Laporan menjawab "berapa"; audit menjawab "siapa mencatat apa, jam berapa" —
dan itu pertanyaan yang muncul justru saat angkanya tidak masuk akal.

Khusus admin ke atas. Layar ini memuat seluruh jejak pencatatan berikut
tombol yang membatalkannya, dan orang yang bisa membatalkan catatannya
sendiri membuat jejak itu tak ada gunanya sebagai jejak. Penjagaannya di
rute (`butuh_admin`), bukan di menu: menyembunyikan pintu bukan penjagaan,
karena alamatnya tetap bisa diketik.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse

from app.database import SessionLocal
from app.services import audit as svc
from app.services import undo as undo_svc
from app.web.security import butuh_admin
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/audit")
async def halaman_audit(
    request: Request,
    rentang: str = Query("48j"),
    kelompok: str = Query("semua"),
    cari: str = Query(""),
    akun=Depends(butuh_admin),
):
    async with SessionLocal() as db:
        catatan, semua = await svc.daftar(
            db, rentang=rentang, kelompok=kelompok, cari=cari)
        # Yang bisa dibatalkan hanya YANG PALING AKHIR. Membatalkan dari
        # tengah berarti angka sesudahnya dihitung dari keadaan yang tak
        # pernah ada.
        pratinjau = await undo_svc.pratinjau_terakhir(db, actor_ids=None)
    return await render_laci(
        request, "audit.html", layar="audit",
        catatan=catatan, semua=semua, pratinjau=pratinjau,
        rentang=rentang, kelompok=kelompok, cari=cari,
        RENTANG=svc.RENTANG, KELOMPOK=svc.KELOMPOK,
        JAM_BATAS=int(svc.BATAS_UBAH.total_seconds() // 3600),
        pesan=request.query_params.get("pesan") or "",
        err=request.query_params.get("err") or "",
    )


@router.post("/audit/batalkan")
async def batalkan_terakhir(
    request: Request,
    rentang: str = Form("48j"),
    kelompok: str = Form("semua"),
    cari: str = Form(""),
    akun=Depends(butuh_admin),
):
    """Batalkan catatan paling akhir — lewat layanan undo yang sudah ada.

    Batas 48 jamnya ditegakkan di dalam `undo_last`, bukan di sini: jalur bot
    memakai fungsi yang sama, dan aturan yang ditulis dua kali cepat atau
    lambat berbeda di salah satunya.
    """
    async with SessionLocal() as db:
        try:
            hasil = await undo_svc.undo_last(
                db, actor=akun.user, actor_ids=None, scope_label=None)
        except undo_svc.UndoError as e:
            kunci, hasil = "err", (e.args[0] if e.args else "Gagal membatalkan.")
        else:
            kunci = "pesan"
    return RedirectResponse(
        "/audit?" + urlencode({"rentang": rentang, "kelompok": kelompok,
                               "cari": cari, kunci: hasil}),
        status_code=303)
