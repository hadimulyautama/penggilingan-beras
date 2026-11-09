"""Daftar komoditas yang boleh masuk ke setiap silo."""
from __future__ import annotations

KOMODITAS_G1 = ("gabah_kering",)
KOMODITAS_G2 = ("pk", "beras_putih", "reject", "broken", "menir")
LABEL_KOMODITAS = {
    "gabah_kering": "Gabah kering",
    "pk": "PK",
    "beras_putih": "Beras putih",
    "reject": "Reject",
    "broken": "Broken",
    "menir": "Menir",
}


def komoditas_g2():
    from app.services.jenis_hasil_samping import _katalog
    return tuple(dict.fromkeys([*KOMODITAS_G2, *[r['kode'] for r in (_katalog.get() or [])]]))


def label_komoditas(kode):
    from app.services.jenis_hasil_samping import nama_samping
    return nama_samping(kode) or LABEL_KOMODITAS.get(kode, kode)


def daftar_diizinkan(silo, gudang: str) -> tuple[str, ...]:
    bawaan = KOMODITAS_G1 if gudang == "g1" or silo.jenis_isi == "gabah" else komoditas_g2()
    tersimpan = silo.komoditas_diizinkan
    if not isinstance(tersimpan, list):
        return bawaan
    # Daftar penuh bawaan lama berarti seluruh komoditas G2. Master baru
    # ikut tersedia tanpa menulis ulang konfigurasi maupun transaksi silo.
    if gudang == "g2" and silo.jenis_isi != "gabah" and set(tersimpan) == set(KOMODITAS_G2):
        return bawaan
    hasil = tuple(k for k in bawaan if k in tersimpan)
    return hasil


def boleh_masuk(silo, komoditas: str, gudang: str) -> bool:
    return komoditas in daftar_diizinkan(silo, gudang)
