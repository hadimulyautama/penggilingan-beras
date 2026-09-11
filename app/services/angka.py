"""Penjaga angka: menolak yang mustahil sebelum ia menular.

Temuan QA P-S-01 & P-K-16, 11 September 2026. Server menerima `nan`, `inf`,
dan angka negatif apa adanya.

**NaN menular, dan itu yang membuatnya jauh lebih berbahaya daripada angka
salah biasa.** Setiap penjumlahan yang menyentuhnya jadi NaN, jadi satu baris
rusak membuat seluruh kolom rusak — stok, laporan, HPP — tanpa satu pun pesan.
Beranda Gudang 1 lalu menjawab 500 untuk SEMUA view karena `int(NaN)`, dan
kegagalannya muncul di layar yang tak ada hubungannya dengan yang mengetik.

Angka negatif lebih sunyi lagi: satu salah ketik tanda minus menghasilkan
total harga −70.344.000 yang masuk laporan apa adanya.

Dijaga di DUA lapis, dan keduanya perlu. Model permintaan menolak di pintu,
tetapi pintu itu tak dilewati semua orang — lapisan AI dan sebagian rute
memanggil layanannya langsung. Penjaga di sini menutup sisanya, dan ia pula
yang dipanggil saat angka datang dari tempat yang belum terpikir.
"""
from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field


class AngkaError(ValueError):
    """Angka yang tak masuk akal — dengan kalimat yang menyebut kolomnya."""


#: Besaran fisik: berat, jumlah, harga. Harus lebih dari nol.
#:
#: `allow_inf_nan=False` bukan hiasan: tanpa itu Pydantic menerima `inf` dan
#: `nan` sebagai float yang sah, dan `gt=0` pun meloloskan `inf`.
Positif = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PositifOpsional = Annotated[float | None, Field(gt=0, allow_inf_nan=False)]

#: Persentase: kadar air, rendemen, butir patah.
Persen = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
PersenOpsional = Annotated[float | None, Field(gt=0, le=100, allow_inf_nan=False)]


def angka_wajar(nilai, nama: str, *, maksimum: float | None = None,
                boleh_nol: bool = False) -> float:
    """Pastikan `nilai` angka yang mungkin ada di dunia nyata.

    `nama` disebut di kalimat galatnya. "Angka tidak valid" tak memberi tahu
    operator harus memperbaiki apa — dan ia sedang berdiri di gudang dengan
    truk menunggu.
    """
    try:
        n = float(nilai)
    except (TypeError, ValueError):
        raise AngkaError(f"{nama} harus berupa angka.") from None
    if math.isnan(n):
        raise AngkaError(f"{nama} bukan angka yang bisa dipakai.")
    if math.isinf(n):
        raise AngkaError(f"{nama} tak terhingga — periksa lagi angkanya.")
    if n < 0:
        raise AngkaError(f"{nama} tidak boleh negatif ({n:g}).")
    if n == 0 and not boleh_nol:
        raise AngkaError(f"{nama} harus lebih dari 0.")
    if maksimum is not None and n > maksimum:
        raise AngkaError(f"{nama} melebihi batas wajar ({n:g} > {maksimum:g}).")
    return n


def angka_opsional(nilai, nama: str, **kw) -> float | None:
    """Sama, tetapi `None` dan kosong dibiarkan lewat — bukan dipaksa nol.

    Memaksa nol pada nilai yang belum diketahui adalah kebohongan yang paling
    mudah dipercaya: ia terbaca sebagai "sudah diukur, hasilnya nol".
    """
    if nilai is None or (isinstance(nilai, str) and not nilai.strip()):
        return None
    return angka_wajar(nilai, nama, **kw)
