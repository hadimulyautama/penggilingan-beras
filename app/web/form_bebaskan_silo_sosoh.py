"""Konteks baca saja untuk satu pemakaian silo G2 yang masih terbuka.

Sisa yang diketik bukan catatan transaksi sampai layanan selesai_penyosohan
menyimpannya. Siklus lama tetap ditampilkan terpisah dan tidak menjadi bahan
siklus baru. Pembaca ini tidak menyinkronkan, mengklaim, atau melepas sumber.
"""
import math
from sqlalchemy import select
from app.models import PolishingProcess, PolishingSiloUsage, Silo, Jasa
from app.penggilingan.gudang2.service import hitung_stok_silo
from app.penggilingan.gudang1.services.bobot import dari_batch
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import nama_pemilik
from app.services.proses_aktif import _waktu


def kunci(nama):
    return (nama or '').strip().casefold().removeprefix('silo ').strip()


async def ringkasan(db, *, kode_proses, silo='', sisa=None, auto_satu=False):
    proc = await db.scalar(select(PolishingProcess).where(
        PolishingProcess.kode_proses == kode_proses))
    if proc is None:
        raise ValueError('Proses penyosohan tidak ditemukan.')
    rows = (await db.execute(select(PolishingSiloUsage, Silo)
        .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
        .where(PolishingSiloUsage.polishing_process_id == proc.id)
        .order_by(PolishingSiloUsage.id))).all()
    terbuka = [(u, si) for u, si in rows if u.berat_akhir_kg is None]
    if auto_satu and not silo and len(terbuka) == 1:
        silo = terbuka[0][1].nama_silo
    target = next(((u, si) for u, si in terbuka if kunci(si.nama_silo) == kunci(silo)), None)
    pemakaian, benda = target if target else (None, None)
    if sisa is not None and not math.isfinite(sisa):
        sisa = None
    awal = float(pemakaian.berat_awal_kg) if pemakaian else None
    tambahan = float(pemakaian.berat_masuk_kg or 0) if pemakaian else None
    bahan = awal + tambahan if pemakaian else None
    # Bantuan berdasarkan angka model yang sama dengan layanan; pemeriksaan
    # kelayakan dan token tetap melalui ringkasan_bebaskan, tidak dari pembaca ini.
    terpakai = max(bahan - sisa, 0.0) if bahan is not None and sisa is not None and 0 <= sisa <= bahan else None
    diketahui = not pemakaian or all(m.berat_kg is not None for m in pemakaian.pemindahan_karung if m.dibatalkan_pada is None)
    final = bool(pemakaian) and all(dari_batch(m.batch).pasti for m in pemakaian.pemindahan_karung if m.dibatalkan_pada is None and m.jumlah_karung is not None)
    jeda = await jeda_terbuka(db, 'penyosohan', proc.id)
    jasa = await db.get(Jasa, proc.jasa_id) if proc.jasa_id else None
    sekarang = []
    for sid in dict.fromkeys(si.id for _, si in rows):
        si = next(si for _, si in rows if si.id == sid)
        sekarang.append(dict(silo=si.nama_silo, status=si.status, kg=await hitung_stok_silo(db, sid)))
    return dict(kode_proses=proc.kode_proses, id=proc.id,
        pemilik=await nama_pemilik(db, proc.jasa_id) if proc.jasa_id else 'Pabrik',
        kepemilikan='Titipan jasa' if proc.jasa_id else 'Milik pabrik',
        pesanan=jasa.kode if jasa else None,
        status='selesai' if proc.status == 'selesai' else 'dijeda' if jeda else 'berjalan',
        sebab_jeda=jeda.sebab if jeda else None, mulai=_waktu(proc.waktu_mulai),
        silo=benda.nama_silo if benda else silo,
        pemakaian_id=pemakaian.id if pemakaian else None, terbuka=bool(pemakaian),
        awal=awal if diketahui else None, tambahan=tambahan if diketahui else None,
        bahan=bahan if diketahui else None, sisa=sisa, terpakai=terpakai if diketahui else None,
        bobot_final=final, bobot_diketahui=diketahui,
        sumber=[dict(id=u.id, silo=si.nama_silo, awal=None if any(m.berat_kg is None for m in u.pemindahan_karung if not m.selama_proses and m.dibatalkan_pada is None) else float(u.berat_awal_kg),
            tambahan=None if any(m.berat_kg is None for m in u.pemindahan_karung if m.selama_proses and m.dibatalkan_pada is None) else float(u.berat_masuk_kg or 0), sisa=float(u.berat_akhir_kg) if u.berat_akhir_kg is not None else None,
            terbuka=u.berat_akhir_kg is None, dinamis=u.bobot_karung_dinamis) for u, si in rows],
        silo_sekarang=sekarang, detail=f'/proses-aktif/sosoh/{proc.kode_proses}')
