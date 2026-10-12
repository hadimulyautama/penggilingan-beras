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


def daftar_diizinkan(silo, gudang: str) -> tuple[str, ...]:
    bawaan = KOMODITAS_G1 if gudang == "g1" else KOMODITAS_G2
    tersimpan = silo.komoditas_diizinkan
    if not isinstance(tersimpan, list):
        return bawaan
    hasil = tuple(k for k in bawaan if k in tersimpan)
    return hasil


def boleh_masuk(silo, komoditas: str, gudang: str) -> bool:
    return komoditas in daftar_diizinkan(silo, gudang)
