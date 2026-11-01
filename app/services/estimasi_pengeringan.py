"""Informasi baca bobot sebelum/sesudah drying; bukan saldo atau mutasi stok.

Indikator mesin memakai kadar air basis basah. Bahan kering diasumsikan
tetap: W akhir = W masuk * (100-KA pertama)/(100-KA selesai).
Jangan gunakan hasil pembaca ini untuk mengganti snapshot transaksi.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.models import (DryingLot, DryingLotBatch, DryingMoistureLog,
                        MillingProcessSource, PurchaseBatch, SiloStorage)
from app.penggilingan.gudang1.services.bobot import Bobot, dari_batches
from hmu_core.proses_db import ProsesTerpadu


def angka(nilai):
    try:
        n = Decimal(str(nilai))
        return n if n.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def hitung(basah, awal, akhir):
    """None berarti tidak layak dihitung, bukan nol atau perkiraan target."""
    w, a, z = map(angka, (basah, awal, akhir))
    if (w is None or a is None or z is None or w <= 0
            or not 0 <= z <= a < 100):
        return None
    return w * (100 - a) / (100 - z)


def format_angka(n, unit='kg'):
    if n is None:
        return None
    s = f'{n:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return f'{s} {unit}'


def ringkas(lot, bobot, logs, *, snapshot_akhir=None, terpakai=False):
    """Satu lot saja. Bacaan alat tes, target, dan log sesudah selesai diabaikan.

    Pencatatan selesai menyimpan indikator di ProsesTerpadu. Log indikatornya
    dapat berselisih mikrodetik dengan waktu selesai karena dua input_time().
    Untuk data lama tanpa snapshot, gunakan log pada/sebelum detik selesai.
    """
    d = dict(kode=lot.kode_lot, basah=format_angka(bobot.kg), kering=None,
             awal=None, akhir=None, waktu_awal=None, waktu_akhir=None,
             catatan=[], historis=terpakai)
    if bobot.tak_diketahui or bobot.kg is None:
        d['basah'] = bobot.teks()
        d['catatan'].append('Bobot masuk belum lengkap; estimasi belum tersedia.')
        return d
    if not bobot.pasti:
        d['basah'] = '≈ ' + d['basah']
        d['catatan'].append('Bobot masuk masih perkiraan.')
    selesai = lot.waktu_selesai_pengeringan
    if not selesai:
        d['catatan'].append('Pengeringan belum selesai; estimasi hasil akhir belum tersedia.')
        return d
    mesin = sorted((x for x in logs if x.kadar_air_indikator is not None
                    and x.waktu_update.replace(microsecond=0) <= selesai.replace(microsecond=0)),
                   key=lambda x: (x.waktu_update, x.id))
    if not mesin:
        d['catatan'].append('Indikator mesin pertama belum tercatat; estimasi belum tersedia.')
        return d
    pertama = mesin[0]
    d['awal'] = format_angka(angka(pertama.kadar_air_indikator), '%')
    d['waktu_awal'] = pertama.waktu_update
    if snapshot_akhir is not None:
        akhir = angka(snapshot_akhir)
        waktu_akhir = selesai
        cukup = pertama.waktu_update.replace(microsecond=0) < selesai.replace(microsecond=0)
    else:
        akhir = angka(mesin[-1].kadar_air_indikator)
        waktu_akhir = mesin[-1].waktu_update
        cukup = len(mesin) >= 2 and mesin[-1].waktu_update > pertama.waktu_update
        d['catatan'].append('Data lama: indikator akhir dari catatan mesin terakhir saat selesai.')
    d.update(akhir=format_angka(akhir, '%'), waktu_akhir=waktu_akhir)
    if not cukup:
        d['catatan'].append('Pasangan indikator awal dan selesai belum lengkap; estimasi belum tersedia.')
        return d
    kg = hitung(bobot.kg, pertama.kadar_air_indikator, akhir)
    if kg is None:
        d['catatan'].append('Indikator mesin tidak sah atau meningkat; estimasi perlu diperiksa.')
        return d
    d['kering'] = format_angka(kg)
    mulai = lot.waktu_mulai_pengeringan
    if mulai and pertama.waktu_update > mulai:
        menit = int((pertama.waktu_update - mulai).total_seconds() // 60)
        d['catatan'].append(f'Bacaan pertama dicatat {menit} menit setelah mulai; bukan pengukuran tepat saat awal.'
                            if menit else 'Bacaan pertama dicatat setelah proses dimulai.')
    if terpakai:
        d['catatan'].append('Bobot sebelum pemakaian berikutnya; bukan saldo sisa silo saat ini.')
    return d


async def untuk_silo_banyak(db, silo_ids):
    """Lima SELECT borongan, tidak bertambah per silo/lot; tidak menulis data."""
    if not silo_ids:
        return {}
    rows = (await db.execute(select(SiloStorage, DryingLot).join(
        DryingLot, DryingLot.id == SiloStorage.drying_lot_id).where(
        SiloStorage.silo_id.in_(silo_ids), SiloStorage.status == 'terisi'))).all()
    if not rows:
        return {}
    used = set(await db.scalars(select(MillingProcessSource.silo_storage_id).where(
        MillingProcessSource.silo_storage_id.in_([r.id for r, _ in rows]),
        MillingProcessSource.berat_akhir_kg.is_not(None))))
    infos = await untuk_lot_banyak(db, [lot for _, lot in rows])
    out = defaultdict(list)
    for row, lot in rows:
        info = dict(infos[lot.id])
        info['historis'] = bool(row.dikemas_kg or row.id in used)
        out[row.silo_id].append(info)
    return dict(out)


async def untuk_lot_banyak(db, lots):
    """Tiga SELECT borongan; berlaku sejak drying selesai, sebelum pindah silo."""
    lots = {lot.id: lot for lot in lots}
    if not lots:
        return {}
    ids = set(lots)
    batches = defaultdict(list)
    for lid, b in (await db.execute(select(DryingLotBatch.drying_lot_id, PurchaseBatch).join(
            PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id).where(
            DryingLotBatch.drying_lot_id.in_(ids)))).all():
        batches[lid].append(b)
    logs = defaultdict(list)
    for log in (await db.scalars(select(DryingMoistureLog).where(
            DryingMoistureLog.drying_lot_id.in_(ids)))).all():
        logs[log.drying_lot_id].append(log)
    snapshots = {r.id_sumber: r for r in (await db.scalars(
        select(ProsesTerpadu).where(ProsesTerpadu.aplikasi == 'produksi',
            ProsesTerpadu.tabel_sumber == 'drying_lots',
            ProsesTerpadu.id_sumber.in_([str(x) for x in ids])))).all()}
    out = {}
    for lot in lots.values():
        sources = batches[lot.id]
        proses = snapshots.get(str(lot.id))
        snapshot = (proses.metadata_domain or {}) if proses else {}
        bobot = dari_batches(sources)
        retur = sum(float(b.retur_supplier_keluar_kg or 0) for b in sources)
        # Angka penerimaan awal tidak menyusut hanya karena ada retur sumber.
        if retur and bobot.kg is not None:
            bobot = Bobot(bobot.kg + retur, bobot.keadaan, bobot.tak_diketahui, bobot.asal)
        info = ringkas(lot, bobot, logs[lot.id],
            snapshot_akhir=snapshot.get('kadar_air_akhir'))
        refs = proses.referensi_asal if proses else []
        if retur or (refs and set(refs) != {b.kode_batch for b in sources}):
            info['kering'] = None
            info['catatan'].append('Komposisi bahan berubah atau memiliki retur sumber; estimasi perlu diperiksa per lot.')
        info['lot_id'] = lot.id
        out[lot.id] = info
    return out
