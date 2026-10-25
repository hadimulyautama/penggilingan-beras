"""Konteks penyelesaian: pembaca saja, tanpa progres, pelepasan atau token baru."""
from decimal import Decimal
from math import isfinite
from sqlalchemy import select
from app.models import MillingProcessSource, MillingProcessVerification, SiloStorage, Silo, DryingLot, PurchaseBatch
from app.penggilingan.gudang1.services import milling as m
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import nama_pemilik
from app.services.proses_aktif import _waktu


async def ringkasan(db, *, kode_proses, berat_akhir=None):
    proc = await m.get_process_by_kode(db, kode_proses.strip())
    if proc is None:
        raise m.MillingError('Proses giling tidak ditemukan.')
    sumber = (await db.execute(select(MillingProcessSource, Silo.nama_silo)
        .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
        .join(Silo, Silo.id == SiloStorage.silo_id)
        .where(MillingProcessSource.milling_process_id == proc.id)
        .order_by(MillingProcessSource.id))).all()
    baris = []
    for r, nama in sumber:
        lot = await db.get(DryingLot, r.drying_lot_id) if r.drying_lot_id else None
        batch = await db.get(PurchaseBatch, r.purchase_batch_id) if r.purchase_batch_id else None
        baris.append(dict(id=r.id, silo=nama, sumber=lot.kode_lot if lot else batch.kode_batch if batch else 'Asal belum tercatat',
            bobot=float(r.berat_kg) if r.berat_kg is not None else None,
            sisa=float(r.berat_akhir_kg) if r.berat_akhir_kg is not None else None,
            terpakai=float(r.berat_terpakai_kg) if r.berat_terpakai_kg is not None else None))
    from app.penggilingan.gudang1.services.silo import silo_ids_proses
    header_silos = list(dict.fromkeys(x['silo'] for x in baris))
    if not header_silos:
        header_silos = list((await db.scalars(select(Silo.nama_silo).where(Silo.id.in_(await silo_ids_proses(db, proc))).order_by(Silo.nama_silo))).all())
    terakhir = await m._latest_progress(db, proc.id)
    final = berat_akhir if berat_akhir is not None else terakhir
    if final is not None and (not isfinite(final) or final <= 0):
        final = None
    verifikasi = await db.scalar(select(MillingProcessVerification.berat_output_final_kg).where(
        MillingProcessVerification.milling_process_id == proc.id))
    awal = await m._pk_breakdown(db, proc.id)
    sesudah = await m._pk_breakdown(db, proc.id, hasil_operator=final) if final is not None else None
    from app.services.retur_penerimaan import berat_kembali
    jeda = await jeda_terbuka(db, 'giling', proc.id)
    lengkap = bool(baris) and all(x['sisa'] is not None for x in baris)
    terpakai = sum(x['terpakai'] for x in baris) if baris and all(x['terpakai'] is not None for x in baris) else None
    return dict(kode_proses=proc.kode_proses, id=proc.id,
        pemilik=await nama_pemilik(db, proc.jasa_id) if proc.jasa_id else 'Pabrik',
        kepemilikan='Titipan jasa' if proc.jasa_id else 'Milik pabrik',
        status='selesai' if proc.status == 'selesai' else ('dijeda' if jeda else 'berjalan') if proc.status == 'proses' else 'belum_diketahui',
        sebab_jeda=jeda.sebab if jeda else None, mulai=_waktu(proc.waktu_mulai),
        silos=header_silos, sumber=baris,
        sisa_lengkap=lengkap, tercatat=terakhir, hasil_akhir=final,
        perubahan=float(Decimal(str(final))-Decimal(str(terakhir))) if final is not None and terakhir is not None else None,
        bobot_acuan=float(proc.berat_gabah_masuk_kg) if proc.berat_gabah_masuk_kg is not None else None,
        bobot_final=proc.bobot_masuk_final, terpakai=terpakai,
        terverifikasi=float(verifikasi) if verifikasi is not None else None,
        stok_sebelum=awal.tersedia, stok_sesudah=sesudah.tersedia if sesudah else None,
        dasar_stok=sesudah.produced if sesudah else awal.produced,
        transfer=awal.transferred, penjualan=await m._sold_pk_langsung(db, proc.id),
        retur=await berat_kembali(db, tipe='pk_langsung', proses_id=proc.id),
        detail=f'/riwayat-giling/{proc.id}' if proc.status == 'selesai' else f'/proses-aktif/giling/{proc.kode_proses}')
