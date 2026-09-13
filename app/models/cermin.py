"""Cermin bertanda: baris tabel lama yang dibatalkan TIDAK dihapus, disaring.

Tahap 3 rancang ulang. Aksi yang sudah di jalur peristiwa menulis cermin ke
tabel lama supaya layar tak berubah. Sampai kini cermin itu DIHAPUS saat
pembatalan, karena belasan pembaca (laporan, stok, tumpukan, rekonsiliasi,
Beranda) menganggap "ada baris" = "ada barang". Menyaring satu per satu di
tiap pembaca adalah cara melewatkan satu.

Maka saringannya SATU, di tingkat sesi: setiap SELECT ORM yang menyentuh
salah satu model di `MODEL_CERMIN` otomatis mendapat `dibatalkan_pada IS
NULL` — termasuk `session.get()`, muatan relasi, dan `select(func.sum(...))`.
Yang memang perlu melihat baris batal (jalur pembatalan, uji) menyebutnya:

    stmt.execution_options(termasuk_dibatalkan=True)

SQL mentah (`text(...)`) TIDAK ikut tersaring — di sana filternya ditulis
eksplisit (tiket timbang, rekonsiliasi). Daftarnya sengaja pendek dan tiap
tempat menyebut komentar "cermin bertanda".
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.penggilingan.gudang1.models import PurchaseBatch
from app.penggilingan.gudang2.models import PkGudang2Intake, PkPurchaseBatch, PkTumpukanToSilo

TERMASUK_DIBATALKAN = "termasuk_dibatalkan"

#: Model yang cerminnya bertanda. Menambah model = menambah di sini DAN
#: memberi kolom `dibatalkan_pada` (migrasi).
MODEL_CERMIN = (PurchaseBatch, PkPurchaseBatch, PkGudang2Intake, PkTumpukanToSilo)


@event.listens_for(Session, "do_orm_execute")
def _saring_cermin(state) -> None:
    if not state.is_select or state.execution_options.get(TERMASUK_DIBATALKAN):
        return
    for model in MODEL_CERMIN:
        state.statement = state.statement.options(
            with_loader_criteria(model, lambda cls: cls.dibatalkan_pada.is_(None),
                                 include_aliases=True))
