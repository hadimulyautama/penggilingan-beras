"""Rute pengawas: ringkasan harian, monitoring pihak, dan ekspor.

Semua halaman di sini butuh peran Pengawas atau Admin — bukan karena datanya
rahasia dari petugas, tetapi karena menilai pola adalah pekerjaan yang berbeda
dari menimbang, dan mencampurnya membuat kedua pekerjaan itu lebih buruk.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import service
from app.timbangan.db import get_db, hari_ini
from app.timbangan.models import TimbanganAkun
from app.timbangan.security import butuh_pengawas
from app.timbangan.web import PREFIX, render

router = APIRouter(prefix=PREFIX)


def _rentang(q) -> tuple[date, date]:
    try:
        dari = date.fromisoformat(q["dari"]) if q.get("dari") else \
            hari_ini() - timedelta(days=30)
        sampai = date.fromisoformat(q["sampai"]) if q.get("sampai") else hari_ini()
    except ValueError:
        dari, sampai = hari_ini() - timedelta(days=30), hari_ini()
    return dari, sampai


@router.get("/laporan")
async def laporan(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    dari, sampai = _rentang(request.query_params)
    f = service.FilterTransaksi(dari=dari, sampai=sampai)
    return render(
        request, "laporan.html",
        f=f,
        ringkasan=await service.ringkasan_dashboard(db, f),
        perlu_periksa=await service.daftar_transaksi(
            db, service.FilterTransaksi(dari=dari, sampai=sampai,
                                        status_kontrol="PERLU_PEMERIKSAAN"),
            batas=20,
        ),
        tara_jatuh_tempo=await service.tara_jatuh_tempo(db),
        kembali=f"{PREFIX}/",
    )


@router.get("/monitoring")
async def monitoring(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    """Skor & pola per pihak.

    Bahasanya selalu 'perlu diperiksa', tidak pernah menuduh. Angka di sini
    adalah alasan untuk bertanya, bukan kesimpulan.
    """
    dari, sampai = _rentang(request.query_params)
    f = service.FilterTransaksi(dari=dari, sampai=sampai)
    return render(
        request, "monitoring.html",
        f=f, baris=await service.monitoring_supplier(db, f),
        kembali=f"{PREFIX}/laporan",
    )


@router.get("/ekspor.csv")
async def ekspor(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    """Ekspor CSV — tanpa satu pun kolom harga, sama seperti seluruh modul."""
    dari, sampai = _rentang(request.query_params)
    baris = await service.daftar_transaksi(
        db, service.FilterTransaksi(dari=dari, sampai=sampai), batas=10_000
    )

    buf = io.StringIO()
    tulis = csv.writer(buf)
    tulis.writerow([
        "kode", "tanggal", "arah", "komoditas", "pihak", "nomor_polisi",
        "timbang1_kg", "jam1", "timbang2_kg", "jam2",
        "netto_timbangan_kg", "jumlah_karung", "total_tara_kg",
        "berat_barang_kg", "berat_acuan_kg", "selisih_kg", "selisih_persen",
        "status_kontrol", "status_tiket", "status_transaksi", "revisi",
    ])
    for b in baris:
        t = b.trx
        tulis.writerow([
            t.kode, t.tanggal, t.arah, t.jenis_kode,
            b.supplier_nama or t.pihak_nama or "", t.nomor_polisi or "",
            t.timbang1_kg, t.timbang1_waktu.strftime("%H:%M") if t.timbang1_waktu else "",
            t.timbang2_kg or "", t.timbang2_waktu.strftime("%H:%M") if t.timbang2_waktu else "",
            t.netto_timbangan_kg or "", t.jumlah_karung, t.total_tara_kg,
            t.berat_barang_kg or "", t.berat_acuan_kg, t.selisih_kg,
            t.selisih_persen, t.status_kontrol or "", t.status_tiket,
            t.status_transaksi, t.jumlah_revisi,
        ])

    buf.seek(0)
    nama = f"timbangan-{dari:%Y%m%d}-{sampai:%Y%m%d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )
