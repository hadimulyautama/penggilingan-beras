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
from sqlalchemy import select

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
from app.models import (MillingProcess, MillingQcLog, PkPurchaseBatch,
                        PkPurchaseVerification, PurchaseBatch, PurchaseBatchQc,
                        PurchaseBatchQcSample)

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


QC_PAGES = {
    "gabah-basah": ("Riwayat QC Gabah Basah", "g1"),
    "gabah-kering": ("Riwayat QC Gabah Kering", "g1"),
    "pk-luar": ("Riwayat QC PK Luar", "g2"),
    "pk-hasil-giling": ("Riwayat QC PK Hasil Giling", "g1"),
    "beras-hasil-sosoh": ("Riwayat QC Beras Hasil Sosoh", "g2"),
}


@router.get("/riwayat-qc/{jenis}")
async def halaman_riwayat_qc(request: Request, jenis: str,
                             akun=Depends(butuh_akun)):
    """Riwayat pengukuran QC; baris mempertahankan isi pencatatan aslinya."""
    if jenis not in QC_PAGES:
        raise HTTPException(404, "Kategori riwayat QC tidak ditemukan.")
    judul, gudang = QC_PAGES[jenis]
    from app.web.api import _is_g1_operator, _is_g2_operator
    boleh = await (_is_g1_operator(akun.user) if gudang == "g1"
                   else _is_g2_operator(akun.user))
    if not boleh:
        raise HTTPException(403, "Riwayat QC ini tidak tersedia untuk peran Anda.")

    grouped: dict[str, dict] = {}

    def tambah(ref: str, waktu, nomor: int | None, detail: list[tuple[str, str]]):
        kartu = grouped.setdefault(ref, {"ref": ref, "rounds": []})
        kartu["rounds"].append({"waktu": waktu, "nomor": nomor,
                                "detail": detail})

    catatan_kosong = None
    async with SessionLocal() as db:
        if jenis in ("gabah-basah", "gabah-kering"):
            kondisi = "basah" if jenis == "gabah-basah" else "kering"
            hasil = (await db.execute(
                select(PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample)
                .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                .join(PurchaseBatchQcSample, PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id)
                .where(PurchaseBatch.kondisi_gabah == kondisi,
                       PurchaseBatch.dibatalkan_pada.is_(None))
                .order_by(PurchaseBatchQcSample.created_at.desc(),
                          PurchaseBatchQcSample.id.desc()).limit(200)
            )).all()
            for batch, _qc, sample in hasil:
                fields = [("Kadar air", f"{sample.kadar_air_1}% dan {sample.kadar_air_2}%"),
                          ("Biji hijau", sample.biji_hijau.replace("_", " ")),
                          ("Densiti", sample.densiti)]
                if kondisi == "basah":
                    fields.insert(1, ("Lamur", f"{'Ya' if sample.lamur else 'Tidak'} · {sample.jumlah_sak_lamur or 0} sak"))
                tambah(batch.kode_batch, sample.created_at,
                       sample.nomor_sampel, fields)
        elif jenis == "pk-luar":
            hasil = (await db.execute(
                select(PkPurchaseBatch, PkPurchaseVerification)
                .join(PkPurchaseVerification,
                      PkPurchaseVerification.pk_purchase_batch_id == PkPurchaseBatch.id)
                .where(PkPurchaseBatch.dibatalkan_pada.is_(None))
                .order_by(PkPurchaseVerification.updated_at.desc(),
                          PkPurchaseVerification.id.desc()).limit(200)
            )).all()
            for batch, qc in hasil:
                values = [("Kadar air", qc.kadar_air, "%"),
                          ("Broken", qc.broken_persen, "%"),
                          ("Penyusutan", qc.penyusutan_persen, "%"),
                          ("Butir kuning", qc.butir_kuning, ""),
                          ("Gabah", qc.gabah, ""), ("Merang", qc.merang, ""),
                          ("Catatan", qc.catatan_lab, "")]
                fields = [(label, f"{value}{unit}") for label, value, unit in values
                          if value is not None and value != ""]
                tambah(batch.kode_batch, qc.updated_at, None,
                       fields or [("QC", "Belum ada hasil QC")])
        elif jenis == "pk-hasil-giling":
            hasil = (await db.execute(
                select(MillingProcess, MillingQcLog)
                .join(MillingQcLog, MillingQcLog.milling_process_id == MillingProcess.id)
                .order_by(MillingQcLog.waktu.desc(), MillingQcLog.id.desc()).limit(200)
            )).all()
            for process, qc in hasil:
                fields = [(label, f"{value}{unit}") for label, value, unit in (
                    ("Kadar air", qc.kadar_air, "%"),
                    ("Broken", qc.broken_persen, "%"),
                    ("Susut", qc.susut_persen, "%"),
                    ("Kondisi", qc.kondisi, "")) if value is not None]
                tambah(process.kode_proses, qc.waktu, None, fields)
        else:
            # Belum ada model/log QC beras hasil sosoh. Jangan menampilkan
            # catatan output sebagai QC karena itu bukan pengukuran mutu.
            catatan_kosong = ("Pencatatan QC beras hasil sosoh belum tersedia. "
                              "Log hasil sosoh yang ada adalah catatan produksi, bukan hasil pengukuran QC.")

    rows = list(grouped.values())
    for kartu in rows:
        kartu["rounds"].sort(key=lambda putaran: (
            putaran["nomor"] is None,
            putaran["nomor"] if putaran["nomor"] is not None else 0,
            putaran["waktu"]
        ))
    rows.sort(key=lambda kartu: max(
        (putaran["waktu"] for putaran in kartu["rounds"] if putaran["waktu"]),
        default=None
    ) or 0, reverse=True)

    return await render_laci(request, "riwayat_qc.html", judul=judul,
                             rows=rows, catatan_kosong=catatan_kosong,
                             jenis=jenis)
