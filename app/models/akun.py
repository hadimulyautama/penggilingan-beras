"""Kredensial masuk — kini model bersama `hmu_identitas.model.Akun`.

Sampai Tahap 2 rancang ulang (13 September 2026) kelas ini didefinisikan di
sini, dengan catatan "bentuknya sudah disiapkan untuk dinaikkan ke paket
bersama kelak bila Timbangan dan Produksi hendak berbagi satu login". Hari
itu tiba: tabelnya tetap `produksi_akun` (tabel lama tak diganti nama —
keputusan pemilik), rantai migrasinya tetap di repo ini, tetapi modelnya
milik paket dan dipakai timbangan juga. Nama `ProduksiAkun` dipertahankan
supaya ratusan pemakainya di repo ini tak perlu disentuh.
"""
from __future__ import annotations

from hmu_identitas.model import Akun as ProduksiAkun, mode_bawaan

__all__ = ["ProduksiAkun", "mode_bawaan"]
