"""Perakitan data dan PDF laporan satu penyosohan yang sudah ditutup."""
from __future__ import annotations
from app.web.qc_warna import NilaiQC, GabunganQC, paragraf, warnai_tabel

from datetime import datetime
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.web.pdf_proses import angka, persen, teks_angka, laju_kadar_air, bagian_jeda, bagian_silo, durasi as durasi_teks


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
            select(PolishingSiloUsage, Silo.nama_silo, Silo.jenis_isi)
            .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
            .where(PolishingSiloUsage.polishing_process_id == proc.id)
            .order_by(PolishingSiloUsage.id)
        )).all()
        if not usages:
            raise HTTPException(404, "Rincian bahan penyosohan tidak ditemukan.")

        # Jenis silo diperlukan untuk membedakan sumber PK dan broken pada
        # rincian neraca. Ambil dari metadata silo, bukan menebak dari namanya.
        silo_ids = {usage.silo_id for usage, _, _ in usages}
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
                    "kind": "broken", "code": move.kode_pindah, "material": "Broken",
                    "owner": owners.get(move.jasa_id) if move.jasa_id else "Pabrik",
                    "plate": "—", "weight": _angka(move.berat_kg),
                }))

        # Putar ledger sekali per silo. Tiap pembebasan mengurangi pool asal;
        # pemakaian ulang tidak boleh memulai lagi dari saldo awal proses.
        from app.models import ActivityLog, BerasKeSilo, HasilSampingKeSilo
        from app.services.asal_silo_pdf import alokasi_sumber
        for model in (BerasKeSilo, HasilSampingKeSilo):
            extra = (await db.scalars(select(model).where(model.silo_id.in_(silo_ids)))).all()
            extra_owners = await nama_pemilik_banyak(db, {x.jasa_id for x in extra if x.jasa_id})
            for move in extra:
                movements[move.silo_id].append((move.waktu, 1, _angka(move.berat_kg), {
                    "kind": "hasil_sosoh", "code": move.kode_pindah,
                    "material": move.jenis.replace('_', ' ').capitalize(),
                    "owner": extra_owners.get(move.jasa_id, "Tidak tercatat") if move.jasa_id else "Pabrik",
                    "plate": "—", "weight": _angka(move.berat_kg)}))
        histories = (await db.execute(select(PolishingSiloUsage, PolishingProcess)
            .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id.in_(silo_ids), PolishingProcess.status != 'dibatalkan')
            .order_by(PolishingSiloUsage.id))).all()
        history_ids = [u.id for u, _ in histories]
        closed_at = {}
        for log in (await db.scalars(select(ActivityLog).where(
            ActivityLog.table_name == 'polishing_silo_usage',
            ActivityLog.aksi == 'tutup_silo_sosoh', ActivityLog.record_id.in_(history_ids),
            ActivityLog.dibatalkan_pada.is_(None)).order_by(ActivityLog.id))).all():
            closed_at[log.record_id] = log.waktu_perubahan
        allocated = alokasi_sumber(movements, histories, closed_at)
        per_silo_sources = []
        for usage, silo_name, silo_kind in usages:
            used = (float(usage.berat_terpakai_kg) if usage.berat_terpakai_kg is not None else
                    float(usage.berat_awal_kg) + _angka(usage.berat_masuk_kg) - float(usage.berat_akhir_kg)
                    if usage.berat_akhir_kg is not None else None)
            per_silo_sources.append({
                "silo": silo_name, "kind": silo_kind, "usage_id": usage.id,
                "start": float(usage.berat_awal_kg), "added": _angka(usage.berat_masuk_kg),
                "remaining": float(usage.berat_akhir_kg) if usage.berat_akhir_kg is not None else None,
                "used": used, "sources": allocated.get(usage.id, []),
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
                previous = per_lot_first.get(lot_code)
                if avg is not None and previous is None:
                    per_lot_first[lot_code] = (log.waktu_update, avg)
                drying_moisture.append({
                    "lot": lot_code, "time": log.waktu_update,
                    "samples": " · ".join(f"{x:g}%" for x in readings) if readings else "Tidak tersedia",
                    "average": f"{avg:.2f}%" if avg is not None else "—",
                    "machine": f"{_angka(log.kadar_air_indikator):g}%" if log.kadar_air_indikator is not None else "—",
                    "speed": laju_kadar_air(previous[1], avg, previous[0], log.waktu_update) if previous else 'Belum dapat dihitung',
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
                "loss": row.susut_persen, "condition": row.kondisi or "—",
                "yellow": row.butir_kuning, "paddy": row.gabah, "chaff": row.merang}
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
        from app.penggilingan.gudang2.karung import bobot_pemakaian
        bobot = bobot_pemakaian([u for u, _, _ in usages])
        total_input = sum(_angka(x["used"]) for x in per_silo_sources)
        neraca = neraca_sosoh(total_input, outputs)
        bahan_tercatat = sum(_angka(u.terpakai_lama_kg) for u, _, _ in usages)
        neraca_tercatat = (neraca_sosoh(bahan_tercatat, outputs)
            if any(u.bobot_karung_dinamis for u, _, _ in usages)
            and abs(bahan_tercatat - total_input) > 0.001 else None)
        from app.web.pdf_proses import jeda_laporan
        jeda = await jeda_laporan(db, jenis='penyosohan', id_=proc.id, mulai=proc.waktu_mulai, selesai=proc.waktu_selesai)
        operator = await db.get(User, proc.created_by)
        from app.models import Jasa
        jasa = await db.get(Jasa, proc.jasa_id) if proc.jasa_id else None
        return {
            "process": proc, "operator": operator.nama if operator else "Tidak tercatat",
            "owner": owners.get(proc.jasa_id) if proc.jasa_id else "Pabrik",
            "jasa": jasa.kode if jasa else None,
            "silos": per_silo_sources, "source_rows": source_rows,
            "batch_sources": batch_source_details, "raw_qc": raw_qc,
            "drying_lots": drying_lots, "drying_moisture": drying_moisture,
            "milling_yields": milling_yields, "milling_qc": milling_qc,
            "external_qc": external_qc, "outputs": outputs,
            "balance": neraca, "neraca_tercatat": neraca_tercatat, "jeda": jeda, "bobot_bahan": bobot, "input_complete": bobot.pasti and all(x["used"] is not None for x in per_silo_sources),
        }


def buat_pdf(data: dict) -> bytes:
    """Penyajian ringkas; sumber angka dan otorisasi tetap pada layanan lama."""
    from app.web.pdf_sosoh import buat_pdf as render
    return render(data)
