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
                        SiloStorage, Silo, MillingProgressLog,
                        MillingProcessVerification)
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


@router.get("/riwayat-giling/{process_id}")
async def detail_riwayat_giling(process_id: int, request: Request,
                               akun=Depends(butuh_akun)):
    from app.web.api import _is_g1_operator
    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Riwayat Penggilingan milik Admin ke atas dan operator Gudang 1.")
    from app.penggilingan.gudang1.services.milling import (
        alasan_koreksi_hasil_giling, riwayat_giling,
    )
    async with SessionLocal() as db:
        kartu, _ = await riwayat_giling(db, batas=1, process_id=process_id)
    if not kartu:
        raise HTTPException(404, "Riwayat penggilingan tidak ditemukan.")
    async with SessionLocal() as db:
        penghalang = (await alasan_koreksi_hasil_giling(db, process_id)
                      if akun.is_admin else None)
    return await render_laci(
        request, "riwayat_detail.html", jenis="giling", k=kartu[0],
        kembali="/riwayat-giling", breadcrumb_detail=kartu[0].kode,
        layar="riwayat_giling", boleh_koreksi=akun.is_admin,
        hasil_awal=kartu[0].hasil_kg, penghalang_koreksi=penghalang,
        hasil_koreksi=request.query_params.get("koreksi") == "berhasil",
        gagal_koreksi=request.query_params.get("koreksi_gagal"),
    )


@router.post("/riwayat-giling/{process_id}/koreksi")
async def koreksi_riwayat_giling(process_id: int, request: Request,
                                 akun=Depends(butuh_akun)):
    if not akun.is_admin:
        raise HTTPException(403, "Koreksi hasil penggilingan hanya untuk Admin ke atas.")
    from app.penggilingan.gudang1.services.milling import MillingError, koreksi_hasil_giling
    form = await request.form()
    try:
        hasil = float(str(form.get("hasil_pk", "")).strip().replace(",", "."))
        dasar = float(str(form.get("dasar_pk", "")).strip().replace(",", "."))
    except (ValueError, TypeError):
        pesan = "Periksa berat hasil PK yang dimasukkan."
        return RedirectResponse(
            f"/riwayat-giling/{process_id}?{urlencode({'koreksi_gagal': pesan})}",
            status_code=303)
    alasan = str(form.get("alasan", "")).strip()
    async with SessionLocal() as db:
        try:
            await koreksi_hasil_giling(
                db, user=akun.user, process_id=process_id,
                hasil_kg=hasil, dasar_kg=dasar, alasan=alasan,
            )
        except MillingError as exc:
            await db.rollback()
            pesan = exc.args[0] if exc.args else "Koreksi hasil tidak dapat disimpan."
            return RedirectResponse(
                f"/riwayat-giling/{process_id}?{urlencode({'koreksi_gagal': pesan})}",
                status_code=303)
    return RedirectResponse(f"/riwayat-giling/{process_id}?koreksi=berhasil", status_code=303)


def _pdf_laporan_giling(data: dict) -> bytes:
    """Susun laporan lengkap satu proses penggilingan sebagai PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, KeepTogether)

    navy, teal = colors.HexColor("#173042"), colors.HexColor("#0B6D83")
    muted, pale, border = (colors.HexColor("#52636D"),
                           colors.HexColor("#EAF2F5"), colors.HexColor("#CCD9DE"))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="GilingTitle", parent=styles["Title"],
                              fontName="Helvetica-Bold", fontSize=18, leading=22,
                              textColor=navy, alignment=TA_LEFT, spaceAfter=3))
    styles.add(ParagraphStyle(name="GilingSub", parent=styles["BodyText"],
                              fontSize=8.5, leading=12, textColor=muted,
                              spaceAfter=10))
    styles.add(ParagraphStyle(name="GilingSection", parent=styles["Heading2"],
                              fontName="Helvetica-Bold", fontSize=11, leading=14,
                              textColor=teal, spaceBefore=9, spaceAfter=5))
    styles.add(ParagraphStyle(name="GilingCell", parent=styles["BodyText"],
                              fontSize=7.5, leading=9.5, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="GilingHead", parent=styles["GilingCell"],
                              fontName="Helvetica-Bold", textColor=colors.white))
    styles.add(ParagraphStyle(name="GilingNote", parent=styles["BodyText"],
                              fontSize=8, leading=10, textColor=muted))

    def p(value, style="GilingCell"):
        return Paragraph(escape(str(value if value not in (None, "") else "—")), styles[style])

    def grid(rows, widths):
        table = Table([[p(cell, "GilingHead" if i == 0 else "GilingCell")
                        for cell in row] for i, row in enumerate(rows)],
                      colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
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
            return "Belum tercatat"
        return f"{float(value):,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".") + " kg"

    def duration(start, end):
        if start is None or end is None:
            return "Belum tercatat"
        secs = max(0, int((end - start).total_seconds()))
        days, secs = divmod(secs, 86400)
        hours, secs = divmod(secs, 3600)
        mins = secs // 60
        return " ".join(([f"{days} hari"] if days else []) +
                        ([f"{hours} jam"] if hours or days else []) +
                        [f"{mins} menit"])

    yield_text = (f"{data['yield']:.1f}%".replace(".", ",")
                  if data["yield"] is not None else "Belum dapat dihitung")
    story = [Paragraph("Laporan Penggilingan Gabah", styles["GilingTitle"]),
             Paragraph(f"{escape(data['kode'])} · Dicetak {stamp(datetime.now(ZoneInfo(settings.app_timezone)))}",
                       styles["GilingSub"])]
    story.append(grid([
        ["Ringkasan proses", "Nilai"],
        ["Pemilik bahan", data["owner"]],
        ["Kondisi gabah", data["class"]],
        ["Komposisi bahan", data["composition"]],
        ["Berat bahan masuk", kg(data["input_kg"])],
        ["Hasil PK · rendemen", f"{kg(data['output_kg'])} · {yield_text}"],
        ["Rata-rata QC", data["qc_summary"]],
        ["Transfer ke Gudang 2", kg(data["transferred_kg"])],
        ["Sisa PK tersedia", kg(data["available_kg"])],
    ], [70 * mm, 100 * mm]))

    story += [Paragraph("Bahan masuk per silo", styles["GilingSection"]),
              Paragraph("Berat saat proses dimulai, berat yang dipakai, dan sisa yang tercatat saat silo dibebaskan.", styles["GilingNote"]),
              Spacer(1, 4)]
    rows = [["Silo", "Sumber", "Berat awal", "Dipakai", "Sisa"]]
    rows += [[x["silo"], x["source"], kg(x["weight"]), kg(x["used"]), kg(x["remaining"])]
             for x in data["sources"]]
    if len(rows) == 1:
        rows.append(["Tidak tercatat", "—", "—", "—", "—"])
    story.append(grid(rows, [30 * mm, 50 * mm, 31 * mm, 31 * mm, 26 * mm]))

    story += [Paragraph("Asal bahan baku", styles["GilingSection"]),
              Paragraph("Batch gabah asal beserta supplier atau pemilik, nomor polisi, dan catatan QC saat penerimaan.", styles["GilingNote"]),
              Spacer(1, 4)]
    rows = [["Batch", "Supplier / pemilik", "No. polisi", "Kondisi", "Berat batch"]]
    rows += [[x["code"], x["origin"], x["plate"], x["condition"], kg(x["weight"])]
             for x in data["batches"]]
    if len(rows) == 1:
        rows.append(["Tidak tercatat", "—", "—", "—", "—"])
    story.append(grid(rows, [34 * mm, 48 * mm, 30 * mm, 26 * mm, 30 * mm]))

    story += [Paragraph("Riwayat pengeringan bahan", styles["GilingSection"]),
              Paragraph("Hanya batch yang melewati pengeringan yang tercantum di sini; batch kering langsung tetap terlihat pada asal bahan baku.", styles["GilingNote"]),
              Spacer(1, 4)]
    rows = [["Lot pengeringan", "Batch asal", "Mulai–selesai pengeringan", "Durasi", "Mulai–selesai pendinginan", "Durasi"]]
    rows += [[x["code"], x["batches"],
              f"{stamp(x['dry_start'])} – {stamp(x['dry_end'])}", duration(x["dry_start"], x["dry_end"]),
              f"{stamp(x['cool_start'])} – {stamp(x['cool_end'])}", duration(x["cool_start"], x["cool_end"])]
             for x in data["drying_lots"]]
    if len(rows) == 1:
        rows.append(["Tidak ada bahan melalui pengeringan", "—", "—", "—", "—", "—"])
    story.append(grid(rows, [34 * mm, 25 * mm, 34 * mm, 20 * mm, 34 * mm, 19 * mm]))

    story += [Paragraph("Pemantauan kadar air saat pengeringan", styles["GilingSection"]), Spacer(1, 4)]
    rows = [["Lot", "Waktu", "Pembacaan sampel", "Rata-rata tes", "Indikator mesin"]]
    rows += [[x["lot"], stamp(x["time"]), x["samples"], x["average"], x["machine"]]
             for x in data["drying_moisture"]]
    if len(rows) == 1:
        rows.append(["Tidak ada catatan pengeringan", "—", "—", "—", "—"])
    story.append(grid(rows, [30 * mm, 38 * mm, 48 * mm, 27 * mm, 25 * mm]))

    rows = [["Batch / QC", "Waktu", "Kadar air", "Lamur", "Biji hijau", "Densiti"]]
    rows += [[x["batch"], stamp(x["time"]), x["moisture"], x["lamur"], x["green"], x["density"]]
             for x in data["raw_qc"]]
    if len(rows) == 1:
        rows.append(["Tidak ada catatan QC", "—", "—", "—", "—", "—"])
    story.append(KeepTogether([
        Paragraph("QC bahan baku", styles["GilingSection"]),
        Paragraph("Setiap pencatatan penerimaan ditampilkan utuh, per batch.", styles["GilingNote"]),
        Spacer(1, 4),
        grid(rows, [32 * mm, 26 * mm, 29 * mm, 24 * mm, 34 * mm, 23 * mm]),
    ]))

    rows = [["Waktu", "Kadar air PK", "Broken", "Susut", "Kondisi"]]
    rows += [[stamp(x["time"]), x["moisture"], x["broken"], x["loss"], x["condition"]]
             for x in data["qc"]]
    if len(rows) == 1:
        rows.append(["Belum ada catatan QC", "—", "—", "—", "—"])
    story.append(KeepTogether([
        Paragraph("QC hasil penggilingan", styles["GilingSection"]),
        Spacer(1, 4),
        grid(rows, [45 * mm, 33 * mm, 28 * mm, 28 * mm, 34 * mm]),
    ]))

    story += [Paragraph("Catatan hasil PK selama proses", styles["GilingSection"]), Spacer(1, 4)]
    rows = [["Waktu catat", "Berat PK kumulatif"]]
    rows += [[stamp(x["time"]), kg(x["weight"])] for x in data["progress"]]
    if len(rows) == 1:
        rows.append(["Belum ada catatan hasil", "—"])
    story.append(grid(rows, [85 * mm, 83 * mm]))

    story += [Paragraph("Riwayat transfer PK", styles["GilingSection"]), Spacer(1, 4)]
    rows = [["Kode transfer", "Waktu", "Tujuan", "Berat"]]
    rows += [[x["code"], stamp(x["time"]), x["destination"], kg(x["weight"])]
             for x in data["transfers"]]
    if len(rows) == 1:
        rows.append(["Belum ada transfer", "—", "—", "—"])
    story.append(grid(rows, [38 * mm, 48 * mm, 50 * mm, 32 * mm]))

    story += [Paragraph("Waktu proses", styles["GilingSection"]),
              grid([["Mulai", "Selesai", "Durasi"],
                    [stamp(data["start"]), stamp(data["end"]), duration(data["start"], data["end"])]],
                   [56 * mm, 56 * mm, 56 * mm])]
    if data["verified_at"]:
        story.append(Paragraph(
            f"Berat hasil PK diverifikasi {stamp(data['verified_at'])}: {escape(kg(data['verified_weight']))}.",
            styles["GilingNote"]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=20 * mm, title=f"Laporan Penggilingan {data['kode']}")

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


async def _ambil_data_laporan_giling(process_id: int) -> dict:
    """Ambil data sumber dan hasil satu proses untuk PDF riwayat giling."""
    from app.models import (DryingLotBatch, DryingLot, DryingMoistureLog, InternalTransfer,
                            MillingProcessSource, MillingProcessVerification,
                            MillingProgressLog, MillingQcLog, PurchaseBatch,
                            PurchaseBatchQc, PurchaseBatchQcSample, Silo,
                            SiloStorage, Supplier)
    from app.penggilingan.gudang1.services.milling import (
        hitung_rendemen, pk_breakdown_banyak, pk_jenis_banyak, qc_rata_banyak)
    from app.services.jasa import nama_pemilik_banyak

    async with SessionLocal() as db:
        process = await db.get(MillingProcess, process_id)
        if process is None or process.status != "selesai":
            raise HTTPException(404, "Riwayat penggilingan tidak ditemukan.")

        source_rows = (await db.execute(
            select(MillingProcessSource, Silo.nama_silo, DryingLot.kode_lot,
                   PurchaseBatch.kode_batch, SiloStorage.tipe_masuk)
            .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
            .join(Silo, Silo.id == SiloStorage.silo_id)
            .outerjoin(DryingLot, DryingLot.id == MillingProcessSource.drying_lot_id)
            .outerjoin(PurchaseBatch, PurchaseBatch.id == MillingProcessSource.purchase_batch_id)
            .where(MillingProcessSource.milling_process_id == process_id)
            .order_by(MillingProcessSource.id)
        )).all()
        sources = []
        batch_ids = set()
        drying_lot_ids = set()
        for source, silo_name, lot_code, batch_code, tipe_masuk in source_rows:
            source_name = (f"{lot_code} · hasil pengeringan" if lot_code else
                           f"{batch_code} · kering langsung" if batch_code and tipe_masuk == "langsung_kering" else
                           batch_code or "Sumber lama")
            sources.append({"silo": silo_name, "source": source_name,
                            "weight": source.berat_kg, "used": source.berat_terpakai_kg,
                            "remaining": source.berat_akhir_kg})
            if source.purchase_batch_id:
                batch_ids.add(source.purchase_batch_id)
            if source.drying_lot_id:
                drying_lot_ids.add(source.drying_lot_id)
                batch_ids.update((await db.execute(
                    select(DryingLotBatch.purchase_batch_id)
                    .where(DryingLotBatch.drying_lot_id == source.drying_lot_id)
                )).scalars().all())

        if not source_rows:
            # Data warisan sebelum milling_process_sources.
            legacy_silo = (await db.execute(select(Silo.nama_silo).where(
                Silo.id == process.silo_id))).scalar_one_or_none()
            source_label = "Sumber lama"
            if process.drying_lot_id:
                drying_lot_ids.add(process.drying_lot_id)
                source_label = (await db.execute(select(DryingLot.kode_lot).where(
                    DryingLot.id == process.drying_lot_id))).scalar_one_or_none() or source_label
                batch_ids.update((await db.execute(select(DryingLotBatch.purchase_batch_id).where(
                    DryingLotBatch.drying_lot_id == process.drying_lot_id))).scalars().all())
            elif process.purchase_batch_id:
                source_label = (await db.execute(select(PurchaseBatch.kode_batch).where(
                    PurchaseBatch.id == process.purchase_batch_id))).scalar_one_or_none() or source_label
                batch_ids.add(process.purchase_batch_id)
            sources.append({"silo": legacy_silo or "Tidak tercatat", "source": source_label,
                            "weight": process.berat_gabah_masuk_kg, "used": None, "remaining": None})

        has_drying = any(row[2] for row in source_rows) if source_rows else bool(process.drying_lot_id)
        has_direct = (any(not row[2] and row[3] and row[4] == "langsung_kering"
                          for row in source_rows) if source_rows
                      else bool(process.purchase_batch_id and not process.drying_lot_id))
        composition = ("Gabah kering langsung + gabah hasil pengeringan" if has_direct and has_drying
                       else "Gabah hasil pengeringan" if has_drying
                       else "Gabah kering langsung" if has_direct
                       else "Sumber bahan lama / tidak lengkap")

        drying_lots = []
        drying_moisture = []
        if drying_lot_ids:
            drying_rows = (await db.execute(select(DryingLot).where(
                DryingLot.id.in_(drying_lot_ids)).order_by(DryingLot.id))).scalars().all()
            lot_batch_rows = (await db.execute(
                select(DryingLotBatch.drying_lot_id, PurchaseBatch.kode_batch)
                .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
                .where(DryingLotBatch.drying_lot_id.in_(drying_lot_ids))
                .order_by(DryingLotBatch.drying_lot_id, PurchaseBatch.id)
            )).all()
            batch_codes_by_lot = {}
            for lot_id, code in lot_batch_rows:
                batch_codes_by_lot.setdefault(lot_id, []).append(code)
            for lot in drying_rows:
                drying_lots.append({
                    "code": lot.kode_lot,
                    "batches": ", ".join(batch_codes_by_lot.get(lot.id, [])) or "Tidak tercatat",
                    "dry_start": lot.waktu_mulai_pengeringan,
                    "dry_end": lot.waktu_selesai_pengeringan,
                    "cool_start": lot.waktu_mulai_pendinginan,
                    "cool_end": lot.waktu_selesai_pendinginan,
                })
            moisture_rows = (await db.execute(
                select(DryingMoistureLog, DryingLot.kode_lot)
                .join(DryingLot, DryingLot.id == DryingMoistureLog.drying_lot_id)
                .where(DryingMoistureLog.drying_lot_id.in_(drying_lot_ids))
                .order_by(DryingMoistureLog.waktu_update, DryingMoistureLog.id)
            )).all()
            for log, lot_code in moisture_rows:
                readings = [getattr(log, f"kadar_air_tes_{i}") for i in range(1, 5)]
                samples = " · ".join(f"{float(v):g}%" for v in readings if v is not None) or "Tidak tercatat"
                drying_moisture.append({
                    "lot": lot_code, "time": log.waktu_update, "samples": samples,
                    "average": f"{float(log.kadar_air_tes_manual):g}%" if log.kadar_air_tes_manual is not None else "—",
                    "machine": f"{float(log.kadar_air_indikator):g}%" if log.kadar_air_indikator is not None else "—",
                })

        batch_rows = []
        if batch_ids:
            batch_rows = (await db.execute(
                select(PurchaseBatch, Supplier.nama_supplier)
                .outerjoin(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(PurchaseBatch.id.in_(batch_ids))
                .order_by(PurchaseBatch.id)
            )).all()
        owner_names = await nama_pemilik_banyak(
            db, {b.jasa_id for b, _ in batch_rows if b.jasa_id} | ({process.jasa_id} if process.jasa_id else set()))
        batches = [{"code": b.kode_batch,
                    "origin": supplier or (owner_names.get(b.jasa_id) if b.jasa_id else "Tidak tercatat"),
                    "plate": b.no_polisi_truk or "Tidak tercatat",
                    "condition": (b.kondisi_gabah or "—").capitalize(),
                    "weight": b.berat_total_kg}
                   for b, supplier in batch_rows]

        raw_qc = []
        if batch_ids:
            rows = (await db.execute(
                select(PurchaseBatch.kode_batch, PurchaseBatch.kondisi_gabah,
                       PurchaseBatchQcSample)
                .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                .join(PurchaseBatchQcSample,
                      PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id)
                .where(PurchaseBatch.id.in_(batch_ids))
                .order_by(PurchaseBatch.id, PurchaseBatchQcSample.nomor_sampel)
            )).all()
            for code, condition, sample in rows:
                raw_qc.append({
                    "batch": f"{code} · QC {sample.nomor_sampel}",
                    "time": sample.created_at,
                    "moisture": f"{float(sample.kadar_air_1):g}% / {float(sample.kadar_air_2):g}%",
                    "lamur": (f"{'Ya' if sample.lamur else 'Tidak'} · {sample.jumlah_sak_lamur or 0} sak"
                              if condition == "basah" else "—"),
                    "green": sample.biji_hijau.replace("_", " "),
                    "density": sample.densiti.capitalize(),
                })

        qc_logs = (await db.execute(select(MillingQcLog)
                                    .where(MillingQcLog.milling_process_id == process_id)
                                    .order_by(MillingQcLog.waktu, MillingQcLog.id))).scalars().all()
        qc = [{"time": row.waktu,
               "moisture": f"{float(row.kadar_air):g}%" if row.kadar_air is not None else "—",
               "broken": f"{float(row.broken_persen):g}%" if row.broken_persen is not None else "—",
               "loss": f"{float(row.susut_persen):g}%" if row.susut_persen is not None else "—",
               "condition": (row.kondisi or "—").upper()} for row in qc_logs]
        progress_logs = (await db.execute(select(MillingProgressLog)
                                          .where(MillingProgressLog.milling_process_id == process_id)
                                          .order_by(MillingProgressLog.waktu_update, MillingProgressLog.id))).scalars().all()
        progress = [{"time": row.waktu_update, "weight": row.berat_kumulatif_kg}
                    for row in progress_logs]
        transfer_rows = (await db.execute(
            select(InternalTransfer, Silo.nama_silo)
            .outerjoin(Silo, Silo.id == InternalTransfer.silo_id)
            .where(InternalTransfer.milling_process_id == process_id,
                   InternalTransfer.status == "terkirim")
            .order_by(InternalTransfer.waktu, InternalTransfer.id)
        )).all()
        transfers = [{
            "code": row.kode_transfer,
            "time": row.waktu,
            "destination": (f"{silo_name} (silo)" if row.lokasi_tujuan == "silo" and silo_name
                            else "Tumpukan" if row.lokasi_tujuan == "ditumpuk"
                            else row.lokasi_tujuan),
            "weight": row.berat_kg,
        } for row, silo_name in transfer_rows]
        breakdown = (await pk_breakdown_banyak(db, [process_id]))[process_id]
        verification = (await db.execute(select(MillingProcessVerification)
                                         .where(MillingProcessVerification.milling_process_id == process_id))).scalar_one_or_none()
        qc_avg = (await qc_rata_banyak(db, [process_id])).get(process_id)
        condition = (await pk_jenis_banyak(db, [process])).get(process_id)
        yield_rate = hitung_rendemen(breakdown.produced, process.berat_gabah_masuk_kg)

        def persen(nilai):
            return f"{nilai:.1f}%".replace(".", ",") if nilai is not None else "Belum ada catatan"

        return {
            "kode": process.kode_proses,
            "owner": owner_names.get(process.jasa_id, "Tidak tercatat") if process.jasa_id else "Pabrik",
            "class": (condition or "Tidak tercatat").upper(),
            "composition": composition,
            "input_kg": process.berat_gabah_masuk_kg,
            "output_kg": breakdown.produced,
            "yield": yield_rate,
            "qc_summary": (
                f"KA {persen(qc_avg.kadar_air)} · Broken {persen(qc_avg.broken)} · Susut {persen(qc_avg.susut)}"
                if qc_avg and qc_avg.ada else "Belum ada catatan QC"
            ),
            "qc_moisture_avg": persen(qc_avg.kadar_air if qc_avg else None),
            "qc_broken_avg": persen(qc_avg.broken if qc_avg else None),
            "qc_loss_avg": persen(qc_avg.susut if qc_avg else None),
            "transferred_kg": breakdown.transferred,
            "available_kg": breakdown.tersedia,
            "sources": sources, "batches": batches, "raw_qc": raw_qc,
            "drying_lots": drying_lots, "drying_moisture": drying_moisture,
            "qc": qc, "progress": progress, "transfers": transfers,
            "start": process.waktu_mulai, "end": process.waktu_selesai,
            "verified_at": verification.waktu_verifikasi if verification else None,
            "verified_weight": verification.berat_output_final_kg if verification else None,
        }


@router.get("/riwayat-giling/{process_id}/laporan.pdf")
async def unduh_laporan_giling(process_id: int, unduh: int = 0,
                              akun=Depends(butuh_akun)):
    from app.web.api import _is_g1_operator
    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Laporan Penggilingan hanya untuk Admin ke atas dan operator Gudang 1.")
    data = await _ambil_data_laporan_giling(process_id)
    pdf = _pdf_laporan_giling(data)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{"attachment" if unduh else "inline"}; filename="laporan-penggilingan-{data["kode"]}.pdf"'})


@router.get("/riwayat-giling/{process_id}/laporan")
async def halaman_laporan_giling(request: Request, process_id: int,
                                akun=Depends(butuh_akun)):
    from app.web.api import _is_g1_operator
    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Laporan Penggilingan hanya untuk Admin ke atas dan operator Gudang 1.")
    async with SessionLocal() as db:
        process = await db.get(MillingProcess, process_id)
        if process is None or process.status != "selesai":
            raise HTTPException(404, "Riwayat penggilingan tidak ditemukan.")
        kode = process.kode_proses
    return await render_laci(
        request, "laporan_giling.html", kode=kode,
        pdf_url=f"/riwayat-giling/{process_id}/laporan.pdf",
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


@router.get("/riwayat-pengeringan/{lot_id}")
async def detail_riwayat_pengeringan(lot_id: int, request: Request,
                                     akun=Depends(butuh_akun)):
    from app.web.api import _is_g1_operator
    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Riwayat Pengeringan milik Admin ke atas dan operator Gudang 1.")
    from app.penggilingan.gudang1.services.drying import riwayat_pengeringan
    async with SessionLocal() as db:
        kartu, _ = await riwayat_pengeringan(db, batas=1, lot_id=lot_id)
    if not kartu:
        raise HTTPException(404, "Riwayat pengeringan tidak ditemukan.")
    return await render_laci(
        request, "riwayat_detail.html", jenis="pengeringan", k=kartu[0],
        kembali="/riwayat-pengeringan", breadcrumb_detail=kartu[0].kode_lot,
        layar="riwayat_pengeringan",
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


@router.get("/riwayat-transfer/{transfer_id}")
async def detail_riwayat_transfer(transfer_id: int, request: Request,
                                  akun=Depends(butuh_akun)):
    from app.web.api import _is_g1_operator
    if not await _is_g1_operator(akun.user):
        raise HTTPException(403, "Riwayat Transfer milik Admin ke atas dan operator Gudang 1.")
    from app.services.transfer import alasan_koreksi_transfer, riwayat_transfer
    async with SessionLocal() as db:
        kartu, _ = await riwayat_transfer(db, batas=1, transfer_id=transfer_id)
    if not kartu:
        raise HTTPException(404, "Riwayat transfer tidak ditemukan.")
    async with SessionLocal() as db:
        penghalang = (await alasan_koreksi_transfer(db, transfer_id)
                      if akun.is_admin else None)
    return await render_laci(
        request, "riwayat_detail.html", jenis="transfer", k=kartu[0],
        kembali="/riwayat-transfer", breadcrumb_detail=kartu[0].kode,
        layar="riwayat_transfer", boleh_koreksi=akun.is_admin,
        hasil_awal=kartu[0].berat_kg, penghalang_koreksi=penghalang,
        hasil_koreksi=request.query_params.get("koreksi") == "berhasil",
        gagal_koreksi=request.query_params.get("koreksi_gagal"),
        pengganti=request.query_params.get("pengganti"),
        pengganti_id=request.query_params.get("pengganti_id"),
    )


@router.post("/riwayat-transfer/{transfer_id}/koreksi")
async def koreksi_riwayat_transfer(transfer_id: int, request: Request,
                                   akun=Depends(butuh_akun)):
    if not akun.is_admin:
        raise HTTPException(403, "Koreksi hasil transfer hanya untuk Admin ke atas.")
    from app.services.transfer import TransferError, koreksi_hasil_transfer
    form = await request.form()
    try:
        berat = float(str(form.get("hasil_transfer", "")).strip().replace(",", "."))
        dasar = float(str(form.get("dasar_transfer", "")).strip().replace(",", "."))
    except (ValueError, TypeError):
        pesan = "Periksa berat transfer yang dimasukkan."
        return RedirectResponse(
            f"/riwayat-transfer/{transfer_id}?{urlencode({'koreksi_gagal': pesan})}",
            status_code=303)
    alasan = str(form.get("alasan", "")).strip()
    async with SessionLocal() as db:
        try:
            pengganti = await koreksi_hasil_transfer(
                db, user=akun.user, transfer_id=transfer_id,
                berat_kg=berat, dasar_kg=dasar, alasan=alasan,
            )
        except TransferError as exc:
            await db.rollback()
            pesan = exc.args[0] if exc.args else "Koreksi hasil tidak dapat disimpan."
            return RedirectResponse(
                f"/riwayat-transfer/{transfer_id}?{urlencode({'koreksi_gagal': pesan})}",
                status_code=303)
    params = {"koreksi": "berhasil"}
    if pengganti is not None:
        params["pengganti"] = pengganti.kode_transfer
        params["pengganti_id"] = pengganti.id
    return RedirectResponse(
        f"/riwayat-transfer/{transfer_id}?{urlencode(params)}", status_code=303)


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
