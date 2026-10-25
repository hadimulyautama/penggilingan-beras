"""Pembaca mix G1; tidak mengklaim sumber, menyinkronkan atau menggabung jasa.

Tambahan memakai _storage_bobot milik layanan. Bahan proses tetap membaca
cuplikan proses, bukan saldo fisik silo yang mungkin sudah dipakai/dilepas.
"""
from sqlalchemy import select
from app.models import Jasa, Pelanggan, MillingProcessSource, Silo, DryingLot, PurchaseBatch
from app.penggilingan.gudang1.services import milling as m, silo as si
from app.penggilingan.gudang1.services.bobot import Bobot, PASTI, PERKIRAAN, TAK_DIKETAHUI, jumlah
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import nama_pemilik, cocok_pemilik


async def pemilik(db, jasa_id):
    if jasa_id is None:
        return "Pabrik"
    # Nama dan kode pesanan ditata terpisah; relasinya tetap ID kontak asli.
    nama = await db.scalar(select(Pelanggan.nama_pelanggan).join(
        Jasa, Jasa.pelanggan_id == Pelanggan.id).where(Jasa.id == jasa_id))
    return nama or await nama_pemilik(db, jasa_id) or "Pemilik belum tercatat"


def bobot_proses(proc, sumber):
    belum = sum(s.berat_kg is None for s in sumber)
    kg = float(proc.berat_gabah_masuk_kg) if proc.berat_gabah_masuk_kg is not None else None
    # Layanan SQL menyimpan bagian diketahui sebagai 0 bila semua sumber NULL.
    # Itu bukan bukti bobot nol; tampilkan keadaan sumber yang sebenarnya.
    if belum and all(s.berat_kg is None for s in sumber):
        kg = None
    keadaan = TAK_DIKETAHUI if belum or kg is None else PASTI if proc.bobot_masuk_final else PERKIRAAN
    return Bobot(kg, keadaan, belum or (1 if kg is None else 0))


async def ringkasan(db, *, kode_proses, silo=""):
    proc = await m.get_process_by_kode(db, kode_proses.strip())
    if proc is None:
        raise m.MillingError("Proses giling tidak ditemukan.")
    sumber = list((await db.scalars(select(MillingProcessSource).where(
        MillingProcessSource.milling_process_id == proc.id).order_by(MillingProcessSource.id))).all())
    sudah = {s.silo_storage_id for s in sumber}
    ids = await si.silo_ids_proses(db, proc)
    silos = list((await db.scalars(select(Silo.nama_silo).where(Silo.id.in_(ids)).order_by(Silo.nama_silo))).all())
    awal = bobot_proses(proc, sumber)
    jeda = await jeda_terbuka(db, 'giling', proc.id)
    jasa = await db.get(Jasa, proc.jasa_id) if proc.jasa_id else None
    rows, rincian, peringatan = [], [], []
    benda = await si.get_g1_silo(db, silo) if silo else None
    if silo:
        if benda is None:
            peringatan.append("Silo tujuan tidak ditemukan atau tidak aktif di Gudang 1.")
        else:
            rows = [r for r in await si._silo_active_rows(db, benda.id) if r.id not in sudah]
            jalan = await si.giling_berjalan_untuk_silo(db, benda.id)
            if jalan and jalan.id != proc.id:
                peringatan.append(f"{benda.nama_silo} sedang digiling ({jalan.kode_proses}). Pilih silo lain.")
            if not rows:
                peringatan.append("Tidak ada sumber baru yang tersedia; isi silo kosong atau sudah terhubung ke proses ini.")
    bobots = []
    for r in rows:
        bobot = await m._storage_bobot(db, r)
        bobots.append(bobot)
        lot = await db.get(DryingLot, r.drying_lot_id) if r.drying_lot_id else None
        batch = await db.get(PurchaseBatch, r.purchase_batch_id) if r.purchase_batch_id else None
        order = await db.get(Jasa, r.jasa_id) if r.jasa_id else None
        rincian.append(dict(id=r.id, sumber=lot.kode_lot if lot else batch.kode_batch if batch else "Asal belum tercatat",
            pemilik=await pemilik(db, r.jasa_id),
            pesanan=order.kode if order else None, bobot=bobot.teks(), final=bobot.pasti))
    cocok = all([await cocok_pemilik(db, proc.jasa_id, r.jasa_id) for r in rows])
    if not cocok:
        peringatan.append("Pemilik bahan berbeda. Bahan pabrik dan jasa, atau pelanggan berbeda, tidak dapat dicampur. Layanan akan menolak penyimpanan.")
    elif any(r.jasa_id != proc.jasa_id for r in rows):
        peringatan.append("Pelanggan sama, pesanan berbeda. Pesanan administratif digabung otomatis oleh layanan saat disimpan; pemilik dan jejak penerimaan tetap tercatat.")
    tambahan = jumlah(bobots) if rows else None
    sesudah = jumlah([awal, tambahan]) if tambahan else None
    if tambahan and not tambahan.pasti:
        peringatan.append("Bobot tambahan belum final. Sumber tetap mengikuti sinkronisasi timbang yang berlaku; total belum lengkap jika ada sumber menunggu timbang.")
    return dict(kode_proses=proc.kode_proses, pemilik=await pemilik(db, proc.jasa_id),
        kepemilikan="Titipan jasa" if proc.jasa_id else "Milik pabrik", pesanan=jasa.kode if jasa else None,
        status="selesai" if proc.status == "selesai" else "dijeda" if jeda else "berjalan" if proc.status == "proses" else "belum diketahui",
        sebab_jeda=jeda.sebab if jeda else None, silos=silos, jumlah_sumber=len(sumber),
        bahan=awal.teks(), bahan_final=awal.pasti, silo=silo,
        nama_silo=benda.nama_silo if benda else silo, sumber=rincian,
        tambahan=tambahan.teks() if tambahan else "Belum tersedia", setelah=sesudah.teks() if sesudah else "Pilih silo dahulu",
        final=sesudah.pasti if sesudah else awal.pasti, cocok=cocok, peringatan=peringatan,
        detail=f"/riwayat-giling/{proc.id}" if proc.status == "selesai" else f"/proses-aktif/giling/{proc.kode_proses}")
