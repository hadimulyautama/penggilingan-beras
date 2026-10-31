"""Otorisasi kartu transit berdasarkan seluruh bahan di tempat yang sama.

Nama silo dan kode kosong mesin bukan nomor transaksi. Menghapus pemeriksaan
kode saja akan mempercayai label pemilik yang dapat tidak konsisten dengan
sumber bahan. Seluruh relasi di sini harus cocok dengan scope baca pelanggan.
"""
from sqlalchemy import func, select

from app.models import (BerasKeSilo, BrokenKeSilo, ByproductStock, CustomerReturn,
                        DryingLot, HasilSampingKeSilo, PkGudang2Intake,
                        PkTumpukanToSilo, PolishingProcess, PolishingSiloUsage,
                        PurchaseBatch)


async def boleh_baca_ruang(db, scope, ruang):
    jenis, ident = ruang
    if jenis == "dryer":
        from app.penggilingan.gudang1.services.drying import _loose_dryer_batches
        batches = await _loose_dryer_batches(db, ident)
        return bool(batches) and all(b.id in scope.ids(PurchaseBatch) for b in batches)
    if jenis == "silo_gabah":
        from app.penggilingan.gudang1.services.silo import _silo_active_rows
        rows = await _silo_active_rows(db, ident)
        return bool(rows) and all(
            r.jasa_id in scope.jasa_ids and
            bool(r.purchase_batch_id or r.drying_lot_id) and
            (not r.purchase_batch_id or r.purchase_batch_id in scope.ids(PurchaseBatch)) and
            (not r.drying_lot_id or r.drying_lot_id in scope.ids(DryingLot))
            for r in rows)
    if jenis != "silo_pk":
        return False
    return await _silo_g2_aman(db, scope, ident)


def _sumber_hasil_aman(scope, jenis, ident):
    if jenis == "polishing":
        return ident in scope.ids(PolishingProcess)
    if jenis == "timbangan":
        return ident in scope.resources.get("timbangan_transaksi", ())
    if jenis == "retur":
        return ident in scope.ids(CustomerReturn)
    return False


async def _silo_g2_aman(db, scope, ident):
    # Riwayat lama tetap tersimpan setelah silo dikosongkan. Batas pengosongan
    # memakai sumber yang sama dengan pemeriksaan bahan proses dalam ReadScope.
    kosong = await db.scalar(select(func.max(PolishingProcess.waktu_selesai))
        .join(PolishingSiloUsage, PolishingSiloUsage.polishing_process_id == PolishingProcess.id)
        .where(PolishingSiloUsage.silo_id == ident,
               PolishingSiloUsage.berat_akhir_kg == 0,
               PolishingProcess.waktu_selesai.is_not(None)))
    def setelah(kolom):
        return [kolom >= kosong] if kosong is not None else []

    intakes = list((await db.scalars(select(PkGudang2Intake).where(
        PkGudang2Intake.silo_id == ident, *setelah(PkGudang2Intake.waktu_masuk)))).all())
    intakes += list((await db.scalars(select(PkGudang2Intake)
        .join(PkTumpukanToSilo, PkTumpukanToSilo.pk_gudang2_intake_id == PkGudang2Intake.id)
        .where(PkTumpukanToSilo.silo_id == ident, *setelah(PkTumpukanToSilo.waktu)))).all())
    if any(i.id not in scope.ids(PkGudang2Intake) for i in intakes):
        return False
    ada = bool(intakes)
    for model in (BrokenKeSilo, BerasKeSilo, HasilSampingKeSilo):
        rows = (await db.scalars(select(model).where(
            model.silo_id == ident, *setelah(model.waktu)))).all()
        ada = ada or bool(rows)
        stocks = {s.id: s for s in (await db.scalars(select(ByproductStock).where(
            ByproductStock.id.in_([r.byproduct_stock_id for r in rows])))).all()} if model is BrokenKeSilo else {}
        for row in rows:
            if row.jasa_id not in scope.jasa_ids:
                return False
            if model is BrokenKeSilo:
                stock = stocks.get(row.byproduct_stock_id)
                if stock is None or stock.jasa_id not in scope.jasa_ids:
                    return False
                if not _sumber_hasil_aman(scope, stock.source_type, stock.source_id):
                    return False
            elif model is HasilSampingKeSilo:
                if row.polishing_process_id not in scope.ids(PolishingProcess):
                    return False
            else:
                if row.polishing_process_id is not None and row.polishing_process_id not in scope.ids(PolishingProcess):
                    return False
                source_id = row.source_id if row.source_id is not None else row.polishing_process_id
                if not _sumber_hasil_aman(scope, row.source_type, source_id):
                    return False
    return ada
