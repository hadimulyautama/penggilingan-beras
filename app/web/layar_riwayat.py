"""Tiga layar "Riwayat Proses" Gudang 1 — Penggilingan, Pengeringan, Transfer.

Sub-menu "Riwayat Proses" (`app/web/nav.py`, kunci `riwayat_sosoh` — ia
sekaligus pintu induk dropdown ini dan pintu "Penyosohan" sendiri, lihat
catatan di sana). Ketiganya di sini satu berkas, pola sama `layar_produk.py`
menampung `/stok-produk` *dan* `/stok-produk-jasa`: tiga layar yang berdiri
sendiri tetapi berbagi gerbang (`_is_g1_operator`) dan bentuk kursor
(`?sebelum=<id>`, pola sama `layar_sosoh.py`).
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci
from app.models import (MillingProcess, MillingQcLog, PkPurchaseBatch,
                        MillingProcessSource, DryingLotBatch,
                        PkPurchaseVerification, PurchaseBatch, PurchaseBatchQc,
                        PurchaseBatchQcSample, Supplier, DryingLot,
                        DryingMoistureLog, Dryer, DryingCoolingLog,
                        SiloStorage, Silo)
from app.config import settings

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


def _pdf_pengeringan(data: dict) -> bytes:
    """Susun laporan satu lot pengeringan sebagai PDF siap unduh."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    navy = colors.HexColor("#173042")
    teal = colors.HexColor("#0B6D83")
    muted = colors.HexColor("#52636D")
    pale = colors.HexColor("#EAF2F5")
    border = colors.HexColor("#CCD9DE")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"],
                              fontName="Helvetica-Bold", fontSize=18, leading=22,
                              textColor=navy, alignment=TA_LEFT, spaceAfter=3))
    styles.add(ParagraphStyle(name="ReportSub", parent=styles["BodyText"],
                              fontSize=8.5, leading=12, textColor=muted,
                              spaceAfter=10))
    styles.add(ParagraphStyle(name="ReportSection", parent=styles["Heading2"],
                              fontName="Helvetica-Bold", fontSize=11, leading=14,
                              textColor=teal, spaceBefore=9, spaceAfter=5))
    styles.add(ParagraphStyle(name="ReportCell", parent=styles["BodyText"],
                              fontSize=7.5, leading=9.5, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="ReportHead", parent=styles["ReportCell"],
                              fontName="Helvetica-Bold", textColor=colors.white))
    styles.add(ParagraphStyle(name="ReportNote", parent=styles["BodyText"],
                              fontSize=8, leading=10, textColor=muted))

    def para(value, style="ReportCell"):
        return Paragraph(escape(str(value if value not in (None, "") else "—")), styles[style])

    def grid(rows, widths):
        table = Table([[para(cell, "ReportHead" if i == 0 else "ReportCell")
                        for cell in row] for i, row in enumerate(rows)],
                      colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), .4, border),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]),
        ]))
        return table

    def stamp(value):
        if value is None:
            return "—"
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(settings.app_timezone))
        return value.strftime("%d/%m/%Y %H:%M") + " WIB"

    def kg(value):
        if value is None:
            return "Belum final"
        return f"{float(value):,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".") + " kg"

    def durasi(start, end):
        if start is None or end is None:
            return "Belum tercatat"
        seconds = max(0, int((end - start).total_seconds()))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        parts = ([f"{days} hari"] if days else [])
        if hours or days:
            parts.append(f"{hours} jam")
        parts.append(f"{minutes} menit")
        return " ".join(parts)

    story = [Paragraph("Laporan Pengeringan Gabah", styles["ReportTitle"]),
             Paragraph(f"{escape(data['kode'])}  ·  Dicetak {stamp(datetime.now(ZoneInfo(settings.app_timezone)))}", styles["ReportSub"])]
    story.append(grid([
        ["Ringkasan lot", "Nilai"],
        ["Pemilik", data["owner"]],
        ["Mesin / mode", data["dryer"]],
        ["Total bahan basah", kg(data["weight"])],
        ["Target kadar air", f"{data['target']}%" if data["target"] is not None else "Tidak ditetapkan"],
        ["Silo tujuan", data["silo"]],
    ], [70 * mm, 100 * mm]))

    story += [Paragraph("Bahan baku dan asal", styles["ReportSection"]),
              Paragraph("Supplier atau pemilik, nomor polisi, dan berat dicantumkan untuk setiap batch.", styles["ReportNote"]),
              Spacer(1, 4)]
    rows = [["Kode batch", "Supplier / pemilik", "No. polisi", "Berat"]]
    rows += [[x["kode"], x["asal"], x["plat"], kg(x["weight"])] for x in data["batches"]]
    story.append(grid(rows, [39 * mm, 51 * mm, 38 * mm, 42 * mm]))

    story += [Paragraph("Riwayat QC bahan baku", styles["ReportSection"]),
              Paragraph("Nilai asli setiap pencatatan ditampilkan; kadar air tidak dirata-ratakan pada riwayat ini.", styles["ReportNote"]),
              Spacer(1, 4)]
    rows = [["Batch / QC", "Waktu", "Kadar air", "Lamur", "Biji hijau", "Densiti"]]
    rows += [[x["batch"], stamp(x["time"]), x["moisture"], x["lamur"], x["green"], x["density"]]
             for x in data["qc"]]
    if len(rows) == 1:
        rows.append(["Tidak ada catatan QC", "—", "—", "—", "—", "—"])
    story.append(grid(rows, [32 * mm, 26 * mm, 29 * mm, 24 * mm, 34 * mm, 23 * mm]))

    story += [Paragraph("Pemantauan kadar air selama proses", styles["ReportSection"]),
              Paragraph("Semua pembacaan alat tes ditampilkan bersama rata-rata catatan dan indikator mesin.", styles["ReportNote"]),
              Spacer(1, 4)]
    rows = [["Waktu catat", "Pembacaan alat tes", "Rata-rata tes", "Indikator mesin", "Rata-rata turun/jam"]]
    rows += [[stamp(x["time"]), x["samples"], x["average"], x["machine"]]
             for x in data["moisture"]]
    for index, row in enumerate(rows[1:]):
        row.append(data["moisture"][index]["speed"])
    if len(rows) == 1:
        rows.append(["Belum ada catatan kadar air", "—", "—", "—", "—"])
    story.append(grid(rows, [35 * mm, 48 * mm, 27 * mm, 29 * mm, 28 * mm]))

    story += [Paragraph("Waktu dan durasi proses", styles["ReportSection"]),
              grid([["Tahap", "Mulai", "Selesai", "Durasi"],
                    ["Pengeringan", stamp(data["dry_start"]), stamp(data["dry_end"]), durasi(data["dry_start"], data["dry_end"])],
                    ["Pendinginan", stamp(data["cool_start"]), stamp(data["cool_end"]), durasi(data["cool_start"], data["cool_end"])],
                    ["Total", stamp(data["dry_start"]), stamp(data["cool_end"]), durasi(data["dry_start"], data["cool_end"]) ]],
                   [35 * mm, 47 * mm, 47 * mm, 51 * mm])]
    if data["cooling_notes"]:
        story.append(Paragraph("Catatan pendinginan", styles["ReportSection"]))
        story.extend(Paragraph(escape(note), styles["ReportNote"]) for note in data["cooling_notes"])

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=20 * mm, title=f"Laporan Pengeringan {data['kode']}")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(border)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, f"Laporan {data['kode']}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Halaman {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


@router.get("/riwayat-pengeringan/{lot_id}/laporan.pdf")
async def unduh_laporan_pengeringan(lot_id: int, unduh: int = 0,
                                    akun=Depends(butuh_akun)):
    """Tampilkan PDF inline, atau unduh sebagai lampiran bila diminta."""
    from app.web.api import _is_g1_operator
    from app.models import DryingLotBatch

    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Laporan Pengeringan hanya untuk Admin ke atas dan operator Gudang 1.")

    async with SessionLocal() as db:
        lot = await db.get(DryingLot, lot_id)
        if lot is None:
            raise HTTPException(404, "Lot pengeringan tidak ditemukan.")
        if lot.waktu_selesai_pendinginan is None:
            raise HTTPException(404, "Laporan tersedia setelah pendinginan selesai.")

        dryer_name = (await db.execute(select(Dryer.nama).where(Dryer.id == lot.dryer_id))).scalar_one_or_none() if lot.dryer_id else None
        batch_rows = (await db.execute(
            select(PurchaseBatch, Supplier.nama_supplier)
            .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
            .outerjoin(Supplier, Supplier.id == PurchaseBatch.supplier_id)
            .where(DryingLotBatch.drying_lot_id == lot.id)
            .order_by(DryingLotBatch.id)
        )).all()
        from app.services.jasa import nama_pemilik_banyak
        owner_names = await nama_pemilik_banyak(db, {b.jasa_id for b, _ in batch_rows if b.jasa_id})
        owner = owner_names.get(lot.jasa_id) if lot.jasa_id else "Pabrik"
        batch_ids = [b.id for b, _ in batch_rows]
        batches = [{"kode": b.kode_batch,
                    "asal": supplier or (owner_names.get(b.jasa_id) if b.jasa_id else "Tidak tercatat"),
                    "plat": b.no_polisi_truk or "Tidak tercatat",
                    "weight": b.berat_total_kg}
                   for b, supplier in batch_rows]

        qc_rows = []
        if batch_ids:
            samples = (await db.execute(
                select(PurchaseBatch.kode_batch, PurchaseBatchQcSample,
                       PurchaseBatchQcSample.created_at)
                .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                .join(PurchaseBatchQcSample, PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id)
                .where(PurchaseBatch.id.in_(batch_ids))
                .order_by(PurchaseBatch.id, PurchaseBatchQcSample.nomor_sampel)
            )).all()
            for kode, sample, created_at in samples:
                is_wet = next((b.kondisi_gabah == "basah" for b, _ in batch_rows if b.kode_batch == kode), False)
                qc_rows.append({
                    "batch": f"{kode} · QC {sample.nomor_sampel}",
                    "time": created_at,
                    "moisture": f"{float(sample.kadar_air_1):g}% / {float(sample.kadar_air_2):g}%",
                    "lamur": (f"{'Ya' if sample.lamur else 'Tidak'} · {sample.jumlah_sak_lamur or 0} sak" if is_wet else "—"),
                    "green": sample.biji_hijau.replace("_", " "),
                    "density": sample.densiti.capitalize(),
                })

        log_rows = (await db.execute(
            select(DryingMoistureLog)
            .where(DryingMoistureLog.drying_lot_id == lot.id)
            .order_by(DryingMoistureLog.waktu_update, DryingMoistureLog.id)
        )).scalars().all()
        moisture = []
        for log in log_rows:
            readings = [getattr(log, f"kadar_air_tes_{n}") for n in range(1, 5)]
            readings = [float(v) for v in readings if v is not None]
            average = (sum(readings) / len(readings) if readings else
                       (float(log.kadar_air_tes_manual) if log.kadar_air_tes_manual is not None else None))
            moisture.append({
                "time": log.waktu_update,
                "samples": " · ".join(f"{v:g}%" for v in readings) if readings else "Tidak tersedia",
                "average": f"{average:.2f}%" if average is not None else "—",
                "machine": f"{float(log.kadar_air_indikator):g}%" if log.kadar_air_indikator is not None else "—",
                "average_value": average,
            })

        # Kecepatan rata-rata adalah penurunan kadar air dari catatan pertama
        # dibagi waktu yang berlalu. Satuannya poin persentase per jam.
        first = next((x for x in moisture if x["average_value"] is not None), None)
        for row in moisture:
            speed = None
            if first and row is not first and row["average_value"] is not None:
                elapsed = (row["time"] - first["time"]).total_seconds() / 3600
                if elapsed > 0:
                    speed = (first["average_value"] - row["average_value"]) / elapsed
            row["speed"] = (f"{speed:.2f}%/jam".replace(".", ",")
                            if speed is not None else "—")

        # Catatan pendinginan disajikan sebagai jejak kejadian tambahan.
        cool_logs = (await db.execute(
            select(DryingCoolingLog)
            .where(DryingCoolingLog.drying_lot_id == lot.id)
            .order_by(DryingCoolingLog.waktu, DryingCoolingLog.id)
        )).scalars().all()
        from app.database import berzona
        cooling_notes = [f"{berzona(row.waktu):%d/%m/%Y %H:%M} WIB: {row.catatan}"
                         for row in cool_logs if row.catatan]
        silo_row = (await db.execute(
            select(Silo.nama_silo)
            .join(SiloStorage, SiloStorage.silo_id == Silo.id)
            .where(SiloStorage.drying_lot_id == lot.id)
            .order_by(SiloStorage.tanggal_masuk.desc()).limit(1)
        )).scalar_one_or_none()

        from app.penggilingan.gudang1.services.bobot import dari_batches
        weight = dari_batches(b for b, _ in batch_rows).angka()
        payload = {
            "kode": lot.kode_lot, "owner": owner or "Tidak tercatat",
            "dryer": f"{dryer_name or 'Tidak tercatat'} / {lot.mode_dryer or 'mode tidak tercatat'}",
            "weight": weight,
            "target": float(lot.target_kadar_air) if lot.target_kadar_air is not None else None,
            "silo": silo_row or "Belum tercatat",
            "batches": batches, "qc": qc_rows, "moisture": moisture,
            "cooling_notes": cooling_notes,
            "dry_start": lot.waktu_mulai_pengeringan,
            "dry_end": lot.waktu_selesai_pengeringan,
            "cool_start": lot.waktu_mulai_pendinginan,
            "cool_end": lot.waktu_selesai_pendinginan,
        }
        pdf = _pdf_pengeringan(payload)

    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'{"attachment" if unduh else "inline"}; filename="laporan-pengeringan-{lot.kode_lot}.pdf"'},
    )


@router.get("/riwayat-pengeringan/{lot_id}/laporan")
async def halaman_laporan_pengeringan(request: Request, lot_id: int,
                                     akun=Depends(butuh_akun)):
    """Penampil laporan di dalam aplikasi dengan kontrol kembali dan berbagi."""
    from app.web.api import _is_g1_operator

    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Laporan Pengeringan hanya untuk Admin ke atas dan operator Gudang 1.")
    async with SessionLocal() as db:
        lot = await db.get(DryingLot, lot_id)
        if lot is None or lot.waktu_selesai_pendinginan is None:
            raise HTTPException(404, "Riwayat pengeringan tidak ditemukan.")
        kode = lot.kode_lot
    return await render_laci(
        request, "laporan_pengeringan.html", kode=kode, lot_id=lot_id,
        pdf_url=f"/riwayat-pengeringan/{lot_id}/laporan.pdf",
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

    def tambah(ref: str, waktu, nomor: int | None, detail: list[tuple[str, str]],
               *, asal: str | None = None, plat: str | None = None):
        kartu = grouped.setdefault(ref, {"ref": ref, "rounds": [],
                                        "asal_set": set(), "plat_set": set()})
        if asal:
            kartu["asal_set"].add(asal)
        if plat:
            kartu["plat_set"].add(plat)
        kartu["rounds"].append({"waktu": waktu, "nomor": nomor,
                                "detail": detail})

    catatan_kosong = None
    async with SessionLocal() as db:
        if jenis in ("gabah-basah", "gabah-kering"):
            kondisi = "basah" if jenis == "gabah-basah" else "kering"
            hasil = (await db.execute(
                select(PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample,
                       Supplier.nama_supplier)
                .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                .join(PurchaseBatchQcSample, PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id)
                .outerjoin(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(PurchaseBatch.kondisi_gabah == kondisi,
                       PurchaseBatch.dibatalkan_pada.is_(None))
                .order_by(PurchaseBatchQcSample.created_at.desc(),
                          PurchaseBatchQcSample.id.desc()).limit(200)
            )).all()
            from app.services.jasa import nama_pemilik_banyak
            pemilik = await nama_pemilik_banyak(db, {b.jasa_id for b, _, _, _ in hasil})
            for batch, _qc, sample, nama_supplier in hasil:
                fields = [("Kadar air", f"{sample.kadar_air_1}% dan {sample.kadar_air_2}%"),
                          ("Biji hijau", sample.biji_hijau.replace("_", " ")),
                          ("Densiti", sample.densiti)]
                if kondisi == "basah":
                    fields.insert(1, ("Lamur", f"{'Ya' if sample.lamur else 'Tidak'} · {sample.jumlah_sak_lamur or 0} sak"))
                tambah(batch.kode_batch, sample.created_at,
                       sample.nomor_sampel, fields,
                       asal=(f"Pemilik jasa: {pemilik[batch.jasa_id]}"
                             if batch.jasa_id in pemilik else
                             f"Supplier: {nama_supplier}" if nama_supplier else None),
                       plat=batch.no_polisi_truk)
        elif jenis == "pk-luar":
            hasil = (await db.execute(
                select(PkPurchaseBatch, PkPurchaseVerification,
                       Supplier.nama_supplier)
                .join(PkPurchaseVerification,
                      PkPurchaseVerification.pk_purchase_batch_id == PkPurchaseBatch.id)
                .outerjoin(Supplier, Supplier.id == PkPurchaseBatch.supplier_id)
                .where(PkPurchaseBatch.dibatalkan_pada.is_(None))
                .order_by(PkPurchaseVerification.updated_at.desc(),
                          PkPurchaseVerification.id.desc()).limit(200)
            )).all()
            from app.services.jasa import nama_pemilik_banyak
            pemilik = await nama_pemilik_banyak(db, {b.jasa_id for b, _, _ in hasil})
            for batch, qc, nama_supplier in hasil:
                values = [("Kadar air", qc.kadar_air, "%"),
                          ("Broken", qc.broken_persen, "%"),
                          ("Penyusutan", qc.penyusutan_persen, "%"),
                          ("Butir kuning", qc.butir_kuning, ""),
                          ("Gabah", qc.gabah, ""), ("Merang", qc.merang, ""),
                          ("Catatan", qc.catatan_lab, "")]
                fields = [(label, f"{value}{unit}") for label, value, unit in values
                          if value is not None and value != ""]
                tambah(batch.kode_batch, qc.updated_at, None,
                       fields or [("QC", "Belum ada hasil QC")],
                       asal=(f"Pemilik jasa: {pemilik[batch.jasa_id]}"
                             if batch.jasa_id in pemilik else
                             f"Supplier: {nama_supplier}" if nama_supplier else None),
                       plat=batch.no_polisi_truk)
        elif jenis == "pk-hasil-giling":
            hasil = (await db.execute(
                select(MillingProcess, MillingQcLog)
                .join(MillingQcLog, MillingQcLog.milling_process_id == MillingProcess.id)
                .order_by(MillingQcLog.waktu.desc(), MillingQcLog.id.desc()).limit(200)
            )).all()
            from app.services.jasa import nama_pemilik_banyak
            pemilik = await nama_pemilik_banyak(db, {p.jasa_id for p, _ in hasil})
            proses_ids = {p.id for p, _ in hasil}
            asal_proses: dict[int, set[str]] = {}
            plat_proses: dict[int, set[str]] = {}
            sumber_langsung = (await db.execute(
                select(MillingProcessSource.milling_process_id,
                       Supplier.nama_supplier, PurchaseBatch.no_polisi_truk)
                .join(PurchaseBatch,
                      PurchaseBatch.id == MillingProcessSource.purchase_batch_id)
                .outerjoin(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(MillingProcessSource.milling_process_id.in_(proses_ids))
            )).all()
            sumber_lot = (await db.execute(
                select(MillingProcessSource.milling_process_id,
                       Supplier.nama_supplier, PurchaseBatch.no_polisi_truk)
                .join(DryingLotBatch,
                      DryingLotBatch.drying_lot_id == MillingProcessSource.drying_lot_id)
                .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
                .outerjoin(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(MillingProcessSource.milling_process_id.in_(proses_ids))
            )).all()
            for proc_id, nama_supplier, no_polisi in (*sumber_langsung, *sumber_lot):
                if nama_supplier:
                    asal_proses.setdefault(proc_id, set()).add(f"Supplier: {nama_supplier}")
                if no_polisi:
                    plat_proses.setdefault(proc_id, set()).add(no_polisi)
            putaran_per_proses: dict[int, int] = {}
            for process, qc in sorted(hasil, key=lambda pair: pair[1].waktu):
                putaran_per_proses[process.id] = putaran_per_proses.get(process.id, 0) + 1
                fields = [(label, f"{value}{unit}") for label, value, unit in (
                    ("Kadar air", qc.kadar_air, "%"),
                    ("Broken", qc.broken_persen, "%"),
                    ("Susut", qc.susut_persen, "%"),
                    ("Kondisi", qc.kondisi, "")) if value is not None]
                asal = ({f"Pemilik jasa: {pemilik[process.jasa_id]}"}
                        if process.jasa_id in pemilik else
                        asal_proses.get(process.id, set()))
                plats = plat_proses.get(process.id, set())
                tambah(process.kode_proses, qc.waktu,
                       putaran_per_proses[process.id], fields,
                       asal=" · ".join(sorted(asal)) or None,
                       plat=" · ".join(sorted(plats)) or None)
        else:
            # Belum ada model/log QC beras hasil sosoh. Jangan menampilkan
            # catatan output sebagai QC karena itu bukan pengukuran mutu.
            catatan_kosong = ("Pencatatan QC beras hasil sosoh belum tersedia. "
                              "Log hasil sosoh yang ada adalah catatan produksi, bukan hasil pengukuran QC.")

    rows = list(grouped.values())
    for kartu in rows:
        kartu["asal"] = " · ".join(sorted(kartu.pop("asal_set"))) or None
        kartu["plat"] = " · ".join(sorted(kartu.pop("plat_set"))) or None
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
