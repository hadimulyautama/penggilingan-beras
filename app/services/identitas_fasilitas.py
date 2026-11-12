"""Identitas tampilan fasilitas; tidak memberi izin atau menghitung saldo."""
from dataclasses import dataclass


@dataclass(frozen=True)
class IdentitasFasilitas:
    warehouse_id: int | None = None
    nama_gudang: str | None = None
    lini_id: int | None = None
    nama_lini: str | None = None

    @property
    def label(self) -> str:
        return ' · '.join(n for n in (self.nama_gudang, self.nama_lini) if n) or 'Fasilitas historis belum tercatat'
