"""Bantuan baca formulir; total, bobot acuan, dan rendemen memakai pembaca lama."""
from math import isfinite

from sqlalchemy import select

from app.models import Silo
from app.penggilingan.gudang1.services import milling
from app.penggilingan.gudang1.services.jeda import jeda_terbuka
from app.penggilingan.gudang1.services.silo import silo_ids_proses
from app.services.jasa import nama_pemilik
from app.services.proses_aktif import _persen


async def ringkasan(db, *, kode_proses: str, berat_kumulatif: float | None = None) -> dict:
    if not kode_proses.strip():
        raise milling.MillingError("Pilih proses giling dulu.")
    proc = await milling.get_process_by_kode(db, kode_proses)
    if proc is None:
        raise milling.MillingError("Proses giling tidak ditemukan.")
    jeda = await jeda_terbuka(db, "giling", proc.id)
    ids = await silo_ids_proses(db, proc)
    silos = (await db.scalars(select(Silo.nama_silo).where(Silo.id.in_(ids))
                             .order_by(Silo.nama_silo))).all()
    # Isian tidak sah tetap ditangani POST lama. Pembaca ini tidak menyimpan,
    # menyinkronkan bobot, atau memakai isi silo sekarang sebagai penyebut.
    total = berat_kumulatif if berat_kumulatif is not None and isfinite(berat_kumulatif) else None
    rendemen = milling.hitung_rendemen(total, proc.berat_gabah_masuk_kg)
    return {
        "kode_proses": proc.kode_proses,
        "tercatat": await milling._latest_progress(db, proc.id),
        "pemilik": (await nama_pemilik(db, proc.jasa_id)) if proc.jasa_id else "Pabrik",
        "kepemilikan": "Titipan jasa" if proc.jasa_id else "Milik pabrik",
        "status": "selesai" if proc.status == "selesai" else "dijeda" if jeda else
                  "berjalan" if proc.status == "proses" else "belum_diketahui",
        "sebab_jeda": jeda.sebab if jeda else None,
        "silos": list(silos),
        "jenis_pk": await milling.pk_jenis(db, proc),
        "bobot_acuan": float(proc.berat_gabah_masuk_kg) if proc.berat_gabah_masuk_kg is not None else None,
        "bobot_final": proc.bobot_masuk_final,
        "rendemen": rendemen,
        "rendemen_teks": _persen(rendemen) if rendemen is not None else "Belum dapat dihitung",
    }
