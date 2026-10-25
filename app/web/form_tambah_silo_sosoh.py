"""Pembaca tambahan G2: saldo lama dan siklus asli, tanpa ikatan/penggabungan.

Pemakaian baru berbeda dari pemakaian akhir. Silo yang dibebaskan dapat
bernilai nol; kelayakan menulis tetap milik tambah_silo_penyosohan.
"""
from sqlalchemy import select
from app.models import (PolishingProcess, PolishingSiloUsage, Silo, Jasa,
    BrokenKeSilo, ByproductStock, BerasKeSilo, HasilSampingKeSilo)
from app.web.form_mulai_penyosohan import baca_silo
from app.web.form_tambah_silo_giling import pemilik
from app.penggilingan.gudang2.service import get_g2_silo, hitung_stok_silo
from app.penggilingan.gudang1.services.bobot import jumlah
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import cocok_pemilik


async def ringkasan(db, *, kode, pilihan):
    proc = await db.scalar(select(PolishingProcess).where(
        PolishingProcess.kode_proses == kode.strip()))
    if proc is None:
        raise ValueError('Proses penyosohan tidak ditemukan.')
    rows = (await db.execute(select(PolishingSiloUsage, Silo).join(Silo,
        Silo.id == PolishingSiloUsage.silo_id).where(
        PolishingSiloUsage.polishing_process_id == proc.id).order_by(PolishingSiloUsage.id))).all()
    pernah = {u.silo_id for u, _ in rows if u.berat_akhir_kg is not None}
    aktif = {u.silo_id for u, _ in rows if u.berat_akhir_kg is None}
    jeda = await jeda_terbuka(db, 'penyosohan', proc.id)
    jasa = await db.get(Jasa, proc.jasa_id) if proc.jasa_id else None
    silos, bobots, peringatan = [], [], []
    if proc.status != 'proses':
        peringatan.append('Proses sudah selesai; silo tidak dapat ditambahkan.')
    pilihan = list(dict.fromkeys(str(x).strip().upper() for x in pilihan if str(x or '').strip()))
    for nama in pilihan:
        silo = await get_g2_silo(db, nama)
        if silo is None:
            silos.append(dict(nama=nama, bobot='Belum tersedia', sumber=[], komposisi=[], pakai_kembali=False, kosong=False, tersedia=False))
            peringatan.append(nama + ' tidak ditemukan pada master aktif Gudang 2.')
            continue
        d, b, ids = await baca_silo(db, silo)
        kg = await hitung_stok_silo(db, silo.id)
        ulang = silo.id in pernah
        d.update(value=nama, pakai_kembali=ulang, kosong=kg <= 0,
            tersedia=(d['proses'] is None and (kg > 0 or ulang)),
            pemakaian_aktif=silo.id in aktif)
        silos.append(d);bobots.append(b)
        if d['proses']:
            peringatan.append(d['nama'] + ' masih dipakai ' + d['proses'] + '. Periksa pilihan terbaru.')
        elif kg <= 0 and not ulang:
            peringatan.append(d['nama'] + ' kosong dan belum mempunyai pemakaian yang dibebaskan pada proses ini.')
        # Cabang kosong mengikuti pembacaan pemilik layanan lama: tanpa
        # pemilik isi, ia tidak dibuat menjadi barang pabrik secara rekaan.
        owners = ids if ids else [None] if kg > 0 else []
        cocok = all([await cocok_pemilik(db, proc.jasa_id, jid) for jid in owners])
        if not cocok:
            peringatan.append(d['nama'] + ': pemilik bahan berbeda dari pemilik proses. Pilih sumber sepemilik.')
        elif any(jid != proc.jasa_id for jid in owners):
            peringatan.append('Pelanggan sama, pesanan berbeda. Pesanan administratif digabung oleh layanan saat disimpan.')
        if not b.pasti:
            peringatan.append(d['nama'] + ': bobot bahan belum final dan tetap mengikuti pembaruan tiket timbang.')
        # Referensi asal yang dibaca ini menjelaskan peringatan saja. Tidak
        # menolak/menulis atau menggantikan pemeriksaan historis saat simpan.
        sendiri = bool(await db.scalar(select(BrokenKeSilo.id).join(ByproductStock,
            ByproductStock.id == BrokenKeSilo.byproduct_stock_id).where(
            BrokenKeSilo.silo_id == silo.id, ByproductStock.source_type == 'polishing',
            ByproductStock.source_id == proc.id).limit(1)))
        for model in (BerasKeSilo, HasilSampingKeSilo):
            sendiri = sendiri or bool(await db.scalar(select(model.id).where(
                model.silo_id == silo.id, model.polishing_process_id == proc.id).limit(1)))
        d['hasil_sendiri'] = sendiri and kg > 0
        if d['hasil_sendiri']:
            peringatan.append(d['nama'] + ' mempunyai hasil proses ini sendiri pada riwayat asal. Pilih sumber lain; layanan memeriksa asal bahan saat disimpan.')
    total = jumlah(bobots) if bobots and len(bobots) == len(pilihan) else None
    return dict(kode=proc.kode_proses, pemilik=await pemilik(db, proc.jasa_id),
        kepemilikan='Titipan jasa' if proc.jasa_id else 'Milik pabrik',
        pesanan=jasa.kode if jasa else None,
        status='selesai' if proc.status != 'proses' else 'dijeda' if jeda else 'berjalan',
        sebab_jeda=jeda.sebab if jeda else None,
        sumber_aktif=list(dict.fromkeys(s.nama_silo for u, s in rows if u.berat_akhir_kg is None)),
        pemakaian=[dict(id=u.id, silo=s.nama_silo, terbuka=u.berat_akhir_kg is None,
            sisa=float(u.berat_akhir_kg) if u.berat_akhir_kg is not None else None) for u, s in rows],
        pilihan=pilihan, silos=silos, tambahan=total.teks() if total else 'Belum dipilih' if not pilihan else 'Belum tersedia',
        final=total.pasti if total else False, peringatan=list(dict.fromkeys(peringatan)),
        detail=f'/proses-aktif/sosoh/{proc.kode_proses}')
