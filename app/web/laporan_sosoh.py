"""Perakitan data dan PDF laporan satu penyosohan yang sudah ditutup."""
from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal


def _angka(value) -> float:
    return float(value or 0)


async def ambil_data(process_id: int) -> dict:
    """Ambil sumber bahan dan jejak proses yang membentuk hasil sosoh."""
    from app.models import (
        BrokenKeSilo, DryingLot, DryingLotBatch, DryingMoistureLog,
        InternalTransfer, MillingProcess, MillingProcessSource, MillingQcLog,
        PkGudang2Intake, PkPurchaseBatch, PkPurchaseVerification,
        PkTumpukanToSilo, PolishingProcess, PolishingSiloUsage,
        PurchaseBatch, PurchaseBatchQcSample, Silo, Supplier, User,
    )
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.inventory.models import ByproductStock
    from app.services.jasa import nama_pemilik_banyak
    from app.services.stok import output_sosoh_banyak
    from app.penggilingan.gudang2.polishing import neraca_sosoh

    async with SessionLocal() as db:
        proc = await db.get(PolishingProcess, process_id)
        if proc is None or proc.status != "selesai":
            raise HTTPException(404, "Riwayat penyosohan tidak ditemukan.")

        usages = (await db.execute(
            select(PolishingSiloUsage, Silo.nama_silo)
            .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
            .where(PolishingSiloUsage.polishing_process_id == proc.id)
            .order_by(PolishingSiloUsage.id)
        )).all()
        if not usages:
            raise HTTPException(404, "Rincian bahan penyosohan tidak ditemukan.")

        # Query memilih tepat dua kolom: objek pemakaian dan nama silo.
        # Membongkar tiga nilai di sini melempar ValueError untuk setiap
        # laporan penyosohan yang punya rincian pemakaian silo.
        silo_ids = {usage.silo_id for usage, _ in usages}
        # Semua pergerakan PK yang masuk langsung ke silo.
        intakes = (await db.execute(
            select(PkGudang2Intake)
            .where(PkGudang2Intake.silo_id.in_(silo_ids))
            .order_by(PkGudang2Intake.waktu_masuk, PkGudang2Intake.id)
        )).scalars().all()
        # PK dari tumpukan mempunyai intake tanpa silo; baris ini yang
        # mencatat kapan dan berapa banyak yang benar-benar masuk ke silo.
        moved_pk = (await db.execute(
            select(PkTumpukanToSilo, PkGudang2Intake)
            .join(PkGudang2Intake,
                  PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id)
            .where(PkTumpukanToSilo.silo_id.in_(silo_ids))
            .order_by(PkTumpukanToSilo.waktu, PkTumpukanToSilo.id)
        )).all()
        broken_moves = (await db.execute(
            select(BrokenKeSilo)
            .where(BrokenKeSilo.silo_id.in_(silo_ids))
            .order_by(BrokenKeSilo.waktu, BrokenKeSilo.id)
        )).scalars().all()

        batch_pk_ids = {x.pk_purchase_batch_id for x in intakes
                        if x.pk_purchase_batch_id}
        batch_pk_ids.update(i.pk_purchase_batch_id for _, i in moved_pk
                            if i.pk_purchase_batch_id)
        transfer_ids = {x.internal_transfer_id for x in intakes
                        if x.internal_transfer_id}
        transfer_ids.update(i.internal_transfer_id for _, i in moved_pk
                            if i.internal_transfer_id)
        pk_batches = {}
        if batch_pk_ids:
            pk_batches = {b.id: (b, supplier) for b, supplier in (await db.execute(
                select(PkPurchaseBatch, Supplier.nama_supplier)
                .outerjoin(Supplier, Supplier.id == PkPurchaseBatch.supplier_id)
                .where(PkPurchaseBatch.id.in_(batch_pk_ids))
            )).all()}
        transfers = {}
        if transfer_ids:
            transfers = {t.id: t for t in (await db.execute(
                select(InternalTransfer).where(InternalTransfer.id.in_(transfer_ids))
            )).scalars().all()}
        milling_ids = {t.milling_process_id for t in transfers.values()}
        milling = {}
        if milling_ids:
            milling = {m.id: m for m in (await db.execute(
                select(MillingProcess).where(MillingProcess.id.in_(milling_ids))
            )).scalars().all()}

        jasa_ids = {proc.jasa_id} if proc.jasa_id else set()
        jasa_ids.update(x.jasa_id for x in broken_moves if x.jasa_id)
        jasa_ids.update(t.jasa_id for t in transfers.values() if t.jasa_id)
        jasa_ids.update(b.jasa_id for b, _ in pk_batches.values() if b.jasa_id)
        owners = await nama_pemilik_banyak(db, jasa_ids)

        # Construye el historial de entradas de cada silo para atribuir el
        # consumo al origen registrado. El contenido físico es mezcla; la
        # distribución por origen es FIFO contable, como en el ledger del silo.
        movements: dict[int, list[tuple]] = {sid: [] for sid in silo_ids}

        def source_for_intake(intake, weight: float) -> dict:
            if intake.pk_purchase_batch_id in pk_batches:
                batch, supplier = pk_batches[intake.pk_purchase_batch_id]
                owner = owners.get(batch.jasa_id) if batch.jasa_id else supplier
                return {
                    "kind": "pk_luar", "code": batch.kode_batch,
                    "material": "PK beli luar", "owner": owner or "Tidak tercatat",
                    "plate": batch.no_polisi_truk or "—", "weight": weight,
                    "pk_batch_id": batch.id,
                }
            transfer = transfers.get(intake.internal_transfer_id)
            if transfer:
                lot = milling.get(transfer.milling_process_id)
                return {
                    "kind": "giling", "code": lot.kode_proses if lot else "LOT tidak tercatat",
                    "material": "PK hasil giling", "owner": owners.get(transfer.jasa_id) if transfer.jasa_id else "Pabrik",
                    "plate": "—", "weight": weight,
                    "milling_id": transfer.milling_process_id,
                }
            return {"kind": "legacy", "code": "Sumber PK lama",
                    "material": "PK", "owner": "Tidak tercatat", "plate": "—",
                    "weight": weight}

        for intake in intakes:
            if intake.silo_id is None:
                continue
            movements[intake.silo_id].append((
                intake.waktu_masuk, 1, _angka(intake.berat_kg),
                source_for_intake(intake, _angka(intake.berat_kg))))
        for move, intake in moved_pk:
            movements[move.silo_id].append((
                move.waktu, 1, _angka(move.berat_kg),
                source_for_intake(intake, _angka(move.berat_kg))))
        for move in broken_moves:
            movements[move.silo_id].append((
                move.waktu, 1, _angka(move.berat_kg), {
                    "kind": "broken", "code": "Stok broken", "material": "Broken",
                    "owner": owners.get(move.jasa_id) if move.jasa_id else "Pabrik",
                    "plate": "—", "weight": _angka(move.berat_kg),
                }))

        # Penarikan dari penyosohan terdahulu mengurangi sumber yang paling
        # lama tercatat. Baris kosong dari proses warisan tetap dicerminkan
        # sebagai saldo tanpa rincian sumber, bukan dibuat-buat sebagai batch.
        previous = (await db.execute(
            select(PolishingSiloUsage, PolishingProcess)
            .join(PolishingProcess,
                  PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id.in_(silo_ids),
                   PolishingProcess.status == "selesai",
                   PolishingProcess.id != proc.id,
                   PolishingProcess.waktu_mulai <= proc.waktu_mulai)
        )).all()
        withdrawals: dict[int, list[tuple]] = {sid: [] for sid in silo_ids}
        for usage, old_proc in previous:
            at = old_proc.waktu_selesai or old_proc.waktu_mulai
            if at and at <= proc.waktu_mulai:
                used = (usage.berat_terpakai_kg if usage.berat_terpakai_kg is not None
                        else _angka(usage.berat_awal_kg) + _angka(usage.berat_masuk_kg)
                        - _angka(usage.berat_akhir_kg))
                withdrawals[usage.silo_id].append((at, -1, max(0, _angka(used)), None))

        per_silo_sources = []
        for usage, silo_name in usages:
            sid = usage.silo_id
            # Replay prior stock entries/withdrawals. Negative first for equal
            # timestamps, following _isian_silo_banyak's zero-boundary rule.
            before = [e for e in movements[sid] if e[0] <= proc.waktu_mulai]
            before += withdrawals[sid]
            before.sort(key=lambda e: (e[0], e[1]))
            pool: list[dict] = []
            for _, sign, amount, source in before:
                if sign > 0:
                    item = dict(source)
                    item["remaining"] = amount
                    pool.append(item)
                else:
                    rest = amount
                    for item in pool:
                        take = min(item["remaining"], rest)
                        item["remaining"] -= take
                        rest -= take
                        if rest <= .005:
                            break
                    pool = [x for x in pool if x["remaining"] > .005]

            expected_start = _angka(usage.berat_awal_kg)
            pool_total = sum(x["remaining"] for x in pool)
            if pool_total < expected_start - .01:
                pool.append({"kind": "legacy", "code": "Saldo silo tanpa rincian sumber",
                             "material": "Bahan campuran",
                             "owner": "Tidak tercatat", "plate": "—",
                             "remaining": expected_start - pool_total})
            elif pool_total > expected_start + .01:
                rest = pool_total - expected_start
                for item in pool:
                    take = min(item["remaining"], rest)
                    item["remaining"] -= take
                    rest -= take
                    if rest <= .005:
                        break
                pool = [x for x in pool if x["remaining"] > .005]

            current_inputs = [e for e in movements[sid]
                              if proc.waktu_mulai < e[0] <= (proc.waktu_selesai or proc.waktu_mulai)]
            current_inputs.sort(key=lambda e: (e[0], e[1]))
            candidates = list(pool)
            for _, _, amount, source in current_inputs:
                item = dict(source)
                item["remaining"] = amount
                candidates.append(item)
            expected_add = _angka(usage.berat_masuk_kg)
            add_total = sum(x["remaining"] for x in candidates[len(pool):])
            if add_total < expected_add - .01:
                candidates.append({"kind": "legacy", "code": "Penambahan tanpa rincian sumber",
                                  "material": "PK" if silo_kind != "broken" else "Broken",
                                  "owner": "Tidak tercatat", "plate": "—",
                                  "remaining": expected_add - add_total})

            used = (usage.berat_terpakai_kg if usage.berat_terpakai_kg is not None
                    else expected_start + expected_add - _angka(usage.berat_akhir_kg))
            rest = max(0.0, _angka(used))
            consumed = []
            for item in candidates:
                take = min(item["remaining"], rest)
                if take > .005:
                    row = dict(item)
                    row["weight"] = take
                    consumed.append(row)
                    item["remaining"] -= take
                    rest -= take
                if rest <= .005:
                    break
            if rest > .01:
                consumed.append({"kind": "legacy", "code": "Bahan tanpa rincian sumber",
                                 "material": "PK" if silo_kind != "broken" else "Broken",
                                 "owner": "Tidak tercatat", "plate": "—", "weight": rest})
            per_silo_sources.append({
                "silo": silo_name, "kind": silo_kind,
                "start": expected_start, "added": expected_add,
                "remaining": _angka(usage.berat_akhir_kg),
                "used": _angka(used), "sources": consumed,
            })

        source_rows = [src for silo in per_silo_sources for src in silo["sources"]]
        used_milling_ids = {x["milling_id"] for x in source_rows if x.get("milling_id")}
        used_pk_ids = {x["pk_batch_id"] for x in source_rows if x.get("pk_batch_id")}

        # Sumber dari proses giling sendiri → batch gabah → QC dan pengeringan.
        mill_processes = [milling[mid] for mid in used_milling_ids if mid in milling]
        milling_sources = []
        if used_milling_ids:
            milling_sources = (await db.execute(
                select(MillingProcessSource)
                .where(MillingProcessSource.milling_process_id.in_(used_milling_ids))
                .order_by(MillingProcessSource.milling_process_id, MillingProcessSource.id)
            )).scalars().all()
        raw_batch_ids = {x.purchase_batch_id for x in milling_sources if x.purchase_batch_id}
        drying_ids = {x.drying_lot_id for x in milling_sources if x.drying_lot_id}
        for m in mill_processes:
            if not any(x.milling_process_id == m.id for x in milling_sources):
                if m.purchase_batch_id:
                    raw_batch_ids.add(m.purchase_batch_id)
                if m.drying_lot_id:
                    drying_ids.add(m.drying_lot_id)
        drying_batches = []
        if drying_ids:
            drying_batches = (await db.execute(
                select(DryingLotBatch).where(DryingLotBatch.drying_lot_id.in_(drying_ids))
            )).scalars().all()
            raw_batch_ids.update(x.purchase_batch_id for x in drying_batches)
        raw_batches = {}
        if raw_batch_ids:
            raw_batches = {b.id: (b, supplier) for b, supplier in (await db.execute(
                select(PurchaseBatch, Supplier.nama_supplier)
                .outerjoin(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(PurchaseBatch.id.in_(raw_batch_ids))
            )).all()}
        raw_owner_ids = {b.jasa_id for b, _ in raw_batches.values() if b.jasa_id}
        raw_owners = await nama_pemilik_banyak(db, raw_owner_ids)
        batch_source_details = []
        raw_qc = []
        for mid in used_milling_ids:
            m = milling.get(mid)
            if m is None:
                continue
            src_rows = [x for x in milling_sources if x.milling_process_id == mid]
            source_ids = {x.purchase_batch_id for x in src_rows if x.purchase_batch_id}
            lot_ids = {x.drying_lot_id for x in src_rows if x.drying_lot_id}
            if not src_rows:
                if m.purchase_batch_id:
                    source_ids.add(m.purchase_batch_id)
                if m.drying_lot_id:
                    lot_ids.add(m.drying_lot_id)
            source_ids.update(x.purchase_batch_id for x in drying_batches
                              if x.drying_lot_id in lot_ids)
            for bid in sorted(source_ids):
                if bid not in raw_batches:
                    continue
                batch, supplier = raw_batches[bid]
                batch_source_details.append({
                    "milling": m.kode_proses, "batch": batch.kode_batch,
                    "condition": (batch.kondisi_gabah or "—").capitalize(),
                    "origin": raw_owners.get(batch.jasa_id) if batch.jasa_id else supplier or "Tidak tercatat",
                    "plate": batch.no_polisi_truk or "—",
                    "weight": _angka(batch.berat_total_kg),
                    "drying": ", ".join(
                        (await db.execute(select(DryingLot.kode_lot).where(
                            DryingLot.id.in_(lot_ids)))).scalars().all()) if lot_ids else "Kering langsung",
                })

        if raw_batch_ids:
            # Gunakan join eksplisit supaya pembacaan tetap sesuai model
            # junction yang dipakai oleh layar Mutu & QC.
            from app.models import PurchaseBatchQc
            qc_rows = (await db.execute(
                select(PurchaseBatch.kode_batch, PurchaseBatch.kondisi_gabah,
                       PurchaseBatchQcSample)
                .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                .join(PurchaseBatchQcSample,
                      PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id)
                .where(PurchaseBatch.id.in_(raw_batch_ids))
                .order_by(PurchaseBatch.kode_batch, PurchaseBatchQcSample.nomor_sampel)
            )).all()
            for code, condition, sample in qc_rows:
                wet = condition == "basah"
                raw_qc.append({
                    "batch": code, "qc": sample.nomor_sampel, "time": sample.created_at,
                    "moisture": f"{_angka(sample.kadar_air_1):g}% / {_angka(sample.kadar_air_2):g}%",
                    "lamur": (f"{'Ya' if sample.lamur else 'Tidak'} · {sample.jumlah_sak_lamur or 0} sak" if wet else "—"),
                    "green": (sample.biji_hijau or "—").replace("_", " "),
                    "density": sample.densiti or "—",
                })

        drying_lots = []
        drying_moisture = []
        if drying_ids:
            lots = (await db.execute(select(DryingLot).where(
                DryingLot.id.in_(drying_ids)).order_by(DryingLot.id))).scalars().all()
            for lot in lots:
                drying_lots.append(lot)
            logs = (await db.execute(
                select(DryingMoistureLog, DryingLot.kode_lot)
                .join(DryingLot, DryingLot.id == DryingMoistureLog.drying_lot_id)
                .where(DryingMoistureLog.drying_lot_id.in_(drying_ids))
                .order_by(DryingMoistureLog.waktu_update, DryingMoistureLog.id)
            )).all()
            per_lot_first = {}
            for log, lot_code in logs:
                readings = [_angka(getattr(log, f"kadar_air_tes_{i}"))
                            for i in range(1, 5)
                            if getattr(log, f"kadar_air_tes_{i}") is not None]
                avg = (_angka(log.kadar_air_tes_manual) if log.kadar_air_tes_manual is not None
                       else sum(readings) / len(readings) if readings else None)
                speed = None
                previous = per_lot_first.get(lot_code)
                if previous and avg is not None:
                    hours = (log.waktu_update - previous[0]).total_seconds() / 3600
                    if hours > 0:
                        speed = (previous[1] - avg) / hours
                if avg is not None and previous is None:
                    per_lot_first[lot_code] = (log.waktu_update, avg)
                drying_moisture.append({
                    "lot": lot_code, "time": log.waktu_update,
                    "samples": " · ".join(f"{x:g}%" for x in readings) if readings else "Tidak tersedia",
                    "average": f"{avg:.2f}%" if avg is not None else "—",
                    "machine": f"{_angka(log.kadar_air_indikator):g}%" if log.kadar_air_indikator is not None else "—",
                    "speed": f"{speed:.2f}%/jam" if speed is not None else "—",
                })

        # QC giling dan rendemen PK untuk setiap lot proses yang menjadi bahan.
        from app.penggilingan.gudang1.services.milling import pk_breakdown_banyak
        breakdowns = await pk_breakdown_banyak(db, list(used_milling_ids)) if used_milling_ids else {}
        milling_yields, milling_qc = [], []
        if used_milling_ids:
            qclogs = (await db.execute(
                select(MillingQcLog).where(MillingQcLog.milling_process_id.in_(used_milling_ids))
                .order_by(MillingQcLog.milling_process_id, MillingQcLog.waktu, MillingQcLog.id)
            )).scalars().all()
            for m in mill_processes:
                result = breakdowns.get(m.id)
                produced = _angka(result.produced) if result else 0
                milling_yields.append({"code": m.kode_proses,
                    "input": _angka(m.berat_gabah_masuk_kg), "output": produced,
                    "yield": produced / _angka(m.berat_gabah_masuk_kg) * 100
                    if _angka(m.berat_gabah_masuk_kg) else None})
            milling_qc = [{"code": row.milling_process_id, "time": row.waktu,
                "moisture": row.kadar_air, "broken": row.broken_persen,
                "loss": row.susut_persen, "condition": row.kondisi or "—"}
                for row in qclogs]
            code_by_id = {m.id: m.kode_proses for m in mill_processes}
            for row in milling_qc:
                row["code"] = code_by_id.get(row["code"], "LOT tidak tercatat")

        external_qc = []
        if used_pk_ids:
            rows = (await db.execute(
                select(PkPurchaseBatch, PkPurchaseVerification, Supplier.nama_supplier)
                .outerjoin(PkPurchaseVerification,
                    PkPurchaseVerification.pk_purchase_batch_id == PkPurchaseBatch.id)
                .outerjoin(Supplier, Supplier.id == PkPurchaseBatch.supplier_id)
                .where(PkPurchaseBatch.id.in_(used_pk_ids))
                .order_by(PkPurchaseBatch.id)
            )).all()
            for batch, qc, supplier in rows:
                external_qc.append({
                    "code": batch.kode_batch,
                    "origin": owners.get(batch.jasa_id) if batch.jasa_id else supplier or "Tidak tercatat",
                    "plate": batch.no_polisi_truk or "—",
                    "time": qc.waktu_verifikasi if qc else None,
                    "moisture": qc.kadar_air if qc else None,
                    "broken": qc.broken_persen if qc else None,
                    "loss": qc.penyusutan_persen if qc else None,
                    "yellow": qc.butir_kuning if qc else None,
                    "paddy": qc.gabah if qc else None,
                    "chaff": qc.merang if qc else None,
                    "decision": qc.keputusan if qc else None,
                })

        outputs = (await output_sosoh_banyak(db, [proc.id])).get(proc.id, {})
        total_input = sum(x["used"] for x in per_silo_sources)
        neraca = neraca_sosoh(total_input, outputs)
        operator = await db.get(User, proc.created_by)
        return {
            "process": proc, "operator": operator.nama if operator else "Tidak tercatat",
            "owner": owners.get(proc.jasa_id) if proc.jasa_id else "Pabrik",
            "silos": per_silo_sources, "source_rows": source_rows,
            "batch_sources": batch_source_details, "raw_qc": raw_qc,
            "drying_lots": drying_lots, "drying_moisture": drying_moisture,
            "milling_yields": milling_yields, "milling_qc": milling_qc,
            "external_qc": external_qc, "outputs": outputs,
            "balance": neraca,
        }


def buat_pdf(data: dict) -> bytes:
    """Render PDF report; uses ordinary PDF so Android can download/share it."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, PageBreak, KeepTogether)
    from app.penggilingan.gudang2.polishing import GRADES
    from app.services.stok import nama_produk

    navy, teal = colors.HexColor("#173042"), colors.HexColor("#0B6D83")
    muted, pale, border = (colors.HexColor("#52636D"), colors.HexColor("#EAF2F5"),
                           colors.HexColor("#CCD9DE"))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SosohTitle", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=navy,
        alignment=TA_LEFT, spaceAfter=3))
    styles.add(ParagraphStyle(name="SosohSub", parent=styles["BodyText"],
        fontSize=8.5, leading=12, textColor=muted, spaceAfter=8))
    styles.add(ParagraphStyle(name="SosohSection", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=teal,
        spaceBefore=7, spaceAfter=4))
    styles.add(ParagraphStyle(name="SosohCell", parent=styles["BodyText"],
        fontSize=7.1, leading=9, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="SosohHead", parent=styles["SosohCell"],
        fontName="Helvetica-Bold", textColor=colors.white))
    styles.add(ParagraphStyle(name="SosohNote", parent=styles["BodyText"],
        fontSize=7.7, leading=10, textColor=muted))

    def p(value, style="SosohCell"):
        return Paragraph(escape(str(value if value not in (None, "") else "—")), styles[style])

    def grid(rows, widths, spans=()):
        table = Table([[p(cell, "SosohHead" if r == 0 else "SosohCell")
                        for cell in row] for r, row in enumerate(rows)],
                      colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("GRID", (0, 0), (-1, -1), .4, border),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]),
        ]))
        for col, first, last in spans:
            table.setStyle(TableStyle([("SPAN", (col, first), (col, last)),
                                       ("VALIGN", (col, first), (col, last), "TOP")]))
        return table

    def stamp(value):
        if value is None:
            return "—"
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(settings.app_timezone))
        return value.strftime("%d/%m/%Y %H:%M") + " WIB"

    def kg(value):
        return f"{_angka(value):,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".") + " kg"

    def pct(value, digits=2):
        return "—" if value is None else f"{float(value):.{digits}f}%".replace(".", ",")

    def duration(start, end):
        if start is None or end is None:
            return "Belum tercatat"
        mins = max(0, int((end - start).total_seconds()) // 60)
        days, mins = divmod(mins, 1440)
        hours, mins = divmod(mins, 60)
        return " ".join(([f"{days} hari"] if days else []) +
                        ([f"{hours} jam"] if hours or days else []) + [f"{mins} menit"])

    proc = data["process"]
    balance = data["balance"]
    output_labels = {"sayur": "Beras Sayur", "medium": "Beras Medium",
                     "medsuper": "Beras Medium Super", "premium": "Beras Premium",
                     "beras_b": "Beras B", "menir": "Menir", "broken": "Broken",
                     "bekatul": "Bekatul", "reject": "Reject"}
    yield_rate = (balance.beras.kg / balance.bahan_kg * 100) if balance.bahan_kg else None
    story = [p("Laporan Penyosohan", "SosohTitle"),
             p(f"{proc.kode_proses} · Dicetak {stamp(datetime.now(ZoneInfo(settings.app_timezone)))}", "SosohSub")]
    story.append(grid([
        ["Ringkasan proses", "Nilai"],
        ["Pemilik bahan", data["owner"]],
        ["Operator", data["operator"]],
        ["Mulai – selesai", f"{stamp(proc.waktu_mulai)} – {stamp(proc.waktu_selesai)}"],
        ["Durasi proses", duration(proc.waktu_mulai, proc.waktu_selesai)],
        ["Total bahan baku", kg(balance.bahan_kg)],
        ["Hasil beras putih · rendemen", f"{kg(balance.beras.kg)} · {pct(yield_rate)}"],
        ["Neraca massa", f"Keluar {kg(balance.keluar_kg)} · susut {kg(balance.susut.kg)} ({pct(balance.susut.persen)})"],
    ], [54 * mm, 106 * mm]))

    story += [Paragraph("Rekap hasil dan rendemen", styles["SosohSection"]), Spacer(1, 3)]
    rows = [["Produk", "Total", "% dari bahan baku"]]
    for kind in [*GRADES, "menir", "broken", "bekatul", "reject"]:
        amount = _angka(data["outputs"].get(kind))
        if amount > 0:
            label = output_labels.get(kind) or nama_produk(kind).capitalize()
            rows.append([label, kg(amount), pct(amount / balance.bahan_kg * 100 if balance.bahan_kg else None)])
    rows += [["Susut (selisih neraca)", kg(balance.susut.kg), pct(balance.susut.persen)],
             ["Total bahan baku", kg(balance.bahan_kg), "100,00%"]]
    story.append(grid(rows, [66 * mm, 50 * mm, 44 * mm]))

    story += [Paragraph("Bahan baku dan jejak asal", styles["SosohSection"]),
              p("Daftar bahan yang benar-benar dipakai per silo. Pembagian sumber pada silo campuran mengikuti FIFO catatan masuk; barang tetap tercampur secara fisik.", "SosohNote"), Spacer(1, 3)]
    rows = [["Silo", "Bahan masuk", "Asal lot / sumber", "Pemilik / supplier", "Berat"]]
    for silo in data["silos"]:
        for src in silo["sources"]:
            rows.append([silo["silo"], src["material"], src["code"],
                         f"{src['owner']} · {src['plate']}" if src["plate"] != "—" else src["owner"],
                         kg(src["weight"])])
    if len(rows) == 1:
        rows.append(["Tidak tercatat", "—", "—", "—", "—"])
    spans = []
    i = 1
    for silo in data["silos"]:
        n = len(silo["sources"])
        if n > 1:
            spans.append((0, i, i + n - 1))
        i += n
    story.append(grid(rows, [30*mm, 27*mm, 39*mm, 43*mm, 21*mm], spans))

    story += [PageBreak(), Paragraph("Rincian sumber bahan", styles["SosohTitle"]),
              Paragraph("Rincian sumber LOT hasil giling", styles["SosohSection"]),
              p("Setiap batch gabah asal memiliki satu baris; LOT yang sama digabung pada kolom pertama.", "SosohNote"), Spacer(1, 3)]
    rows = [["LOT hasil giling", "Batch gabah asal · berat", "Supplier / pemilik · no. polisi", "Tahap sebelum giling", "Rujukan QC"]]
    spans = []
    grouped = {}
    for item in data["batch_sources"]:
        grouped.setdefault(item["milling"], []).append(item)
    for lot_code, items in grouped.items():
        start = len(rows)
        for item in items:
            rows.append([lot_code if len(rows) == start else "",
                         f"{item['batch']} · {item['condition'].lower()} · {kg(item['weight'])}",
                         f"{item['origin']} · {item['plate']}",
                         f"{item['drying']} → giling" if item["drying"] != "Kering langsung" else "Kering langsung → giling",
                         f"QC gabah {item['condition'].lower()}" if item["condition"] != "—" else "QC gabah"])
        if len(items) > 1:
            spans.append((0, start, len(rows) - 1))
    if len(rows) == 1:
        rows.append(["Tidak ada lot giling yang tercatat", "—", "—", "—", "—"])
    story.append(grid(rows, [29*mm, 43*mm, 37*mm, 31*mm, 34*mm], spans))

    if data["milling_yields"]:
        story += [Paragraph("Rendemen PK dari proses giling sendiri", styles["SosohSection"]), Spacer(1, 3)]
        rows = [["Lot giling", "Gabah masuk", "PK dihasilkan", "Rendemen PK"]]
        rows += [[x["code"], kg(x["input"]), kg(x["output"]), pct(x["yield"])]
                 for x in data["milling_yields"]]
        story.append(grid(rows, [64*mm, 38*mm, 36*mm, 36*mm]))

    external = [x for x in data["source_rows"] if x["kind"] == "pk_luar"]
    if external:
        story += [Paragraph("Rincian sumber PK dari luar", styles["SosohSection"]),
                  p("Nomor polisi menunjukkan armada pembawa lot PK.", "SosohNote"), Spacer(1, 3)]
        rows = [["LOT PK luar", "Pemasok / pemilik", "No. polisi armada", "Berat dipakai", "Rujukan QC"]]
        rows += [[x["code"], x["owner"], x["plate"], kg(x["weight"]), "QC PK luar"]
                 for x in external]
        story.append(grid(rows, [35*mm, 39*mm, 34*mm, 28*mm, 38*mm]))

    story += [PageBreak(), Paragraph("Rincian QC bahan dan proses asal", styles["SosohTitle"]),
              p("Nilai tiap pencatatan QC gabah ditampilkan utuh. Kadar air dibaca dua kali per sampel.", "SosohSub")]
    batch_names = {}
    for item in data["batch_sources"]:
        batch_names[item["batch"]] = item
    for code, item in batch_names.items():
        condition = item["condition"].lower()
        rows = [["QC", "Waktu", "Kadar air 1 / 2", "Lamur", "Biji hijau", "Densiti"]]
        samples = [x for x in data["raw_qc"] if x["batch"] == code]
        for x in samples:
            rows.append([f"QC {x['qc']}", stamp(x["time"]), x["moisture"],
                         x["lamur"] if condition == "basah" else "—", x["green"], x["density"]])
        if len(rows) == 1:
            rows.append(["Belum ada pencatatan QC", "—", "—", "—", "—", "—"])
        story += [Paragraph(f"QC gabah {condition} · {code} · {item['origin']} · {item['plate']}", styles["SosohSection"]),
                  grid(rows, [15*mm, 31*mm, 34*mm, 29*mm, 31*mm, 26*mm])]

    if data["external_qc"]:
        story += [Paragraph("QC PK dari luar", styles["SosohSection"]),
                  p("Sistem menyimpan satu catatan verifikasi per LOT PK luar; laporan menampilkan nilai yang tercatat.", "SosohNote"), Spacer(1, 3)]
        rows = [["LOT / supplier · plat", "Waktu QC", "KA", "Broken", "Susut", "Butir kuning / gabah / merang", "Keputusan"]]
        for x in data["external_qc"]:
            rows.append([f"{x['code']} · {x['origin']} · {x['plate']}", stamp(x["time"]),
                pct(x["moisture"]), pct(x["broken"]), pct(x["loss"]),
                " / ".join(str(v or "—") for v in [x["yellow"], x["paddy"], x["chaff"]]),
                x["decision"] or "Belum dicatat"])
        story.append(grid(rows, [38*mm, 27*mm, 16*mm, 18*mm, 16*mm, 36*mm, 16*mm]))

    story += [PageBreak(), Paragraph("Rincian QC proses giling dan pengeringan", styles["SosohTitle"]),
              Paragraph("QC giling disajikan per LOT, QC 1 dan seterusnya satu baris per pencatatan.", styles["SosohSub"]),
              Paragraph("QC proses giling", styles["SosohSection"])]
    rows = [["Lot giling", "QC", "Waktu", "KA", "Broken", "Susut", "Kondisi"]]
    spans = []
    grouped_qc = {}
    for x in data["milling_qc"]:
        grouped_qc.setdefault(x["code"], []).append(x)
    for code, logs in grouped_qc.items():
        start = len(rows)
        for index, x in enumerate(logs, 1):
            rows.append([code if index == 1 else "", f"QC {index}", stamp(x["time"]),
                         pct(x["moisture"]), pct(x["broken"]), pct(x["loss"]), x["condition"]])
        if len(logs) > 1:
            spans.append((0, start, len(rows)-1))
    if len(rows) == 1:
        rows.append(["Belum ada catatan QC giling", "—", "—", "—", "—", "—", "—"])
    story.append(grid(rows, [37*mm, 15*mm, 27*mm, 19*mm, 23*mm, 19*mm, 29*mm], spans))

    if data["drying_lots"]:
        story += [Paragraph("Pengeringan dan pendinginan bahan asal", styles["SosohSection"]), Spacer(1, 3)]
        rows = [["Lot pengeringan", "Mulai pengeringan", "Selesai", "Durasi pengeringan", "Mulai pendinginan", "Selesai", "Durasi pendinginan"]]
        rows += [[lot.kode_lot, stamp(lot.waktu_mulai_pengeringan), stamp(lot.waktu_selesai_pengeringan),
                  duration(lot.waktu_mulai_pengeringan, lot.waktu_selesai_pengeringan),
                  stamp(lot.waktu_mulai_pendinginan), stamp(lot.waktu_selesai_pendinginan),
                  duration(lot.waktu_mulai_pendinginan, lot.waktu_selesai_pendinginan)]
                 for lot in data["drying_lots"]]
        story.append(grid(rows, [22*mm, 24*mm, 24*mm, 24*mm, 24*mm, 24*mm, 27*mm]))
        story += [Paragraph("Pemantauan kadar air saat pengeringan", styles["SosohSection"]), Spacer(1, 3)]
        rows = [["Lot", "Waktu", "Pembacaan alat tes", "Rata-rata tes", "Indikator mesin", "Rata-rata turun/jam"]]
        rows += [[x["lot"], stamp(x["time"]), x["samples"], x["average"], x["machine"], x["speed"]]
                 for x in data["drying_moisture"]]
        if len(rows) == 1:
            rows.append(["Tidak ada catatan", "—", "—", "—", "—", "—"])
        story.append(grid(rows, [22*mm, 29*mm, 41*mm, 25*mm, 25*mm, 27*mm]))
    else:
        story.append(p("Tidak ada batch bahan yang melalui pengeringan sebelum digiling.", "SosohNote"))
    story.append(p("QC proses sosoh belum memiliki catatan terpisah di sistem.", "SosohNote"))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
        topMargin=15*mm, bottomMargin=19*mm, title=f"Laporan Penyosohan {proc.kode_proses}")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(border)
        canvas.line(18*mm, 14*mm, A4[0]-18*mm, 14*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(18*mm, 9*mm, f"Laporan {proc.kode_proses}")
        canvas.drawRightString(A4[0]-18*mm, 9*mm, f"Halaman {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
