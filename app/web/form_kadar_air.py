"""Konteks dan pratinjau pengukuran, hanya baca dan memakai helper resmi."""
from math import isfinite

from app.models import Dryer, DryingMoistureLog
from app.penggilingan.gudang1.services import drying as dr
from app.penggilingan.gudang1.services.bobot import dari_batches
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import nama_pemilik
from app.services.proses_aktif import _persen


async def ringkasan(db, *, kode_lot, tes=(), indikator=None):
    if not kode_lot.strip():
        raise dr.DryingError("Pilih pengeringan dulu.")
    lot = await dr.get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise dr.DryingError("Pengeringan tidak ditemukan.")
    if (len(tes) > 4 or any(not isfinite(x) or not 0 < x <= 100 for x in tes)
            or (indikator is not None and (not isfinite(indikator) or not 0 < indikator <= 100))):
        raise dr.DryingError("Isikan bacaan yang sah: lebih dari 0 dan maksimal 100%.")
    rata, sebar, selisih = dr.ringkasan_bacaan(sampel=tes, indikator=indikator)
    # Objek belum tersimpan hanya menyediakan bentuk yang dibaca helper
    # peringatan. Tidak ditambahkan ke sesi, tidak menjadi log sintetis.
    titik = list(tes) + [None] * 4
    bacaan = DryingMoistureLog(
        kadar_air_tes_manual=rata, kadar_air_indikator=indikator,
        **{'kadar_air_tes_' + str(i + 1): titik[i] for i in range(4)})
    jeda = await jeda_terbuka(db, 'pengeringan', lot.id)
    dryer = await db.get(Dryer, lot.dryer_id) if lot.dryer_id else None
    bahan = await dr._lot_batches(db, lot.id)
    return {
        'kode_lot': lot.kode_lot,
        'pemilik': await nama_pemilik(db, lot.jasa_id) if lot.jasa_id else 'Pabrik',
        'kepemilikan': 'Titipan jasa' if lot.jasa_id else 'Milik pabrik',
        'dryer': dryer.nama if dryer else 'Dryer belum tercatat',
        'bahan': dari_batches(bahan).teks(), 'batch': [x.kode_batch for x in bahan],
        'status': ('selesai' if lot.status == 'selesai' else 'dijeda' if jeda else
                   'berjalan' if lot.status == 'proses' else 'belum_diketahui'),
        'sebab_jeda': jeda.sebab if jeda else None,
        'target': float(lot.target_kadar_air) if lot.target_kadar_air is not None else None,
        'target_teks': _persen(lot.target_kadar_air) if lot.target_kadar_air is not None else 'Belum tercatat',
        'rata': rata, 'sebar': sebar, 'selisih': selisih, 'jumlah_titik': len(tes),
        'rata_teks': _persen(rata) if rata is not None else 'Belum dapat dihitung',
        'sebar_teks': _persen(sebar) if sebar is not None else 'Perlu minimal dua titik',
        'mesin_teks': _persen(indikator) if indikator is not None else 'Belum diisi',
        'selisih_teks': f'{selisih:+.1f}%'.replace('.', ',') if selisih is not None else 'Belum dapat dihitung',
        'peringatan': dr.peringatan_kadar_air(bacaan),
    }
