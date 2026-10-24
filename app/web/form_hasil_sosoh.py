"""Konteks baca formulir, tanpa pratinjau transaksi atau rumus hasil kedua."""
from sqlalchemy import select

from app.models import PolishingSiloUsage, Silo
from app.penggilingan.gudang2.polishing import (
    Gudang2Error, _ALL_JENIS, _get_proc, _total_output,
)
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.services.jasa import nama_pemilik


async def ringkasan(db, *, kode_proses: str, jenis: str = "") -> dict:
    if not kode_proses.strip():
        raise Gudang2Error("Pilih proses penyosohan dulu.")
    jenis = jenis.strip().lower()
    if jenis and jenis not in _ALL_JENIS:
        raise Gudang2Error("Pilih jenis hasil yang dikenali.")
    proc = await _get_proc(db, kode_proses)
    jeda = await jeda_terbuka(db, "penyosohan", proc.id)
    usages = (await db.execute(select(Silo.nama_silo, PolishingSiloUsage.berat_akhir_kg)
        .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
        .where(PolishingSiloUsage.polishing_process_id == proc.id)
        .order_by(PolishingSiloUsage.id))).all()
    return {
        "kode_proses": proc.kode_proses,
        "jenis": jenis,
        # None bukan nol: sebelum memilih jenis, total belum diminta.
        # Helper ini juga yang dipanggil catat_output setelah mengunci proses.
        "tercatat": await _total_output(db, proc.id, jenis) if jenis else None,
        "pemilik": (await nama_pemilik(db, proc.jasa_id)) if proc.jasa_id else "Pabrik",
        "kepemilikan": "Titipan jasa" if proc.jasa_id else "Milik pabrik",
        "status": "selesai" if proc.status == "selesai" else "dijeda" if jeda else
                  "berjalan" if proc.status == "proses" else "belum_diketahui",
        "sebab_jeda": jeda.sebab if jeda else None,
        "silos": [{"nama": nama, "dipakai": sisa is None} for nama, sisa in usages],
    }
