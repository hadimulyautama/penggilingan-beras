"""Otorisasi kartu transit berdasarkan seluruh bahan di tempat yang sama.

Nama silo dan kode kosong mesin bukan nomor transaksi. Menghapus pemeriksaan
kode saja akan mempercayai label pemilik yang dapat tidak konsisten dengan
sumber bahan. Seluruh relasi di sini harus cocok dengan scope baca pelanggan.
"""
from sqlalchemy import func, select, or_
from app.performa import baca_sekali

from app.models import (BerasKeSilo, BrokenKeSilo, ByproductStock, CustomerReturn,
                        DryingLot, HasilSampingKeSilo, PkGudang2Intake,
                        PkTumpukanToSilo, PolishingProcess, PolishingSiloUsage,
                        PurchaseBatch)


@baca_sekali
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
    return (await _silo_g2_banyak(db, scope)).get(ident, False)


@baca_sekali
async def _silo_g2_banyak(db, scope):
    """Pemeriksaan sumber yang sama, sekaligus untuk seluruh silo.

    Batas kosong dan syarat pemilik/sumber tetap identik. Sebelumnya setiap
    silo memerlukan enam SELECT walaupun kosong; Beranda pelanggan membaca
    silo-silo itu lagi saat menggambar bahan. Scope tetap berasal dari
    pemeriksaan akun/relasi baru di setiap permintaan, tanpa cache izin
    lintas permintaan maupun pengabaian sumber campuran.
    """
    from app.models import Silo
    silos = list((await db.scalars(select(Silo.id))).all())
    if not silos:
        return {}
    # [ada bahan, seluruh bahan aman]
    keadaan = {sid: [False, True] for sid in silos}
    batas = (select(PolishingSiloUsage.silo_id.label("silo"),
                    func.max(PolishingProcess.waktu_selesai).label("kosong"))
        .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.berat_akhir_kg == 0,
               PolishingProcess.waktu_selesai.is_not(None))
        .group_by(PolishingSiloUsage.silo_id).subquery())

    def berlaku(q, silo, waktu):
        return q.outerjoin(batas, batas.c.silo == silo).where(
            silo.in_(silos), or_(batas.c.kosong.is_(None), waktu >= batas.c.kosong))

    def intake(silo_id, identitas):
        keadaan[silo_id][0] = True
        if identitas not in scope.ids(PkGudang2Intake):
            keadaan[silo_id][1] = False

    for row in (await db.scalars(berlaku(select(PkGudang2Intake),
            PkGudang2Intake.silo_id, PkGudang2Intake.waktu_masuk))).all():
        intake(row.silo_id, row.id)
    pindah = berlaku(select(PkTumpukanToSilo.silo_id, PkGudang2Intake.id)
        .join(PkGudang2Intake, PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id),
        PkTumpukanToSilo.silo_id, PkTumpukanToSilo.waktu)
    for sid, identitas in (await db.execute(pindah)).all():
        intake(sid, identitas)

    for model in (BrokenKeSilo, BerasKeSilo, HasilSampingKeSilo):
        rows = (await db.scalars(berlaku(select(model), model.silo_id, model.waktu))).all()
        stocks = {s.id: s for s in (await db.scalars(select(ByproductStock).where(
            ByproductStock.id.in_([r.byproduct_stock_id for r in rows])))).all()} if model is BrokenKeSilo and rows else {}
        for row in rows:
            kondisi = keadaan[row.silo_id]
            kondisi[0] = True
            aman = row.jasa_id in scope.jasa_ids
            if model is BrokenKeSilo:
                stock = stocks.get(row.byproduct_stock_id)
                aman = (aman and stock is not None and stock.jasa_id in scope.jasa_ids
                        and _sumber_hasil_aman(scope, stock.source_type, stock.source_id))
            elif model is HasilSampingKeSilo:
                aman = aman and row.polishing_process_id in scope.ids(PolishingProcess)
            else:
                aman = (aman and (row.polishing_process_id is None
                        or row.polishing_process_id in scope.ids(PolishingProcess))
                        and _sumber_hasil_aman(scope, row.source_type,
                            row.source_id if row.source_id is not None else row.polishing_process_id))
            kondisi[1] = kondisi[1] and aman
    return {sid: ada and aman for sid, (ada, aman) in keadaan.items()}
