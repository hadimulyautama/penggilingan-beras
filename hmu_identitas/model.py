"""Akun bersama — satu baris kredensial untuk satu orang di `users`.

Tabelnya `produksi_akun`: dibuat Pos Produksi (Fase B), dan sejak Tahap 2
dipakai semua aplikasi. Namanya tak diganti — keputusan pemilik: tabel lama
tak diganti nama, awalan modul hanya untuk tabel baru. Rantai migrasinya
tetap milik produksi sampai tabel master dipindahkan ke `core` (tahap kecil
tersendiri).

Sengaja HANYA kredensial. Nama, peran, gudang bawaan tinggal di `users` dan
dibaca lewat relasi; tak ada kolom peran di sini — begitu peran tersalin di
dua tempat, cepat atau lambat keduanya berbeda.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hmu_core import Base, TimestampMixin, User

from . import peran as P

BERSAMA, PRIBADI = "bersama", "pribadi"
AKTIF, NONAKTIF = "aktif", "nonaktif"


class Akun(Base, TimestampMixin):
    __tablename__ = "produksi_akun"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: aktif | nonaktif — CERMIN dari `users.status` yang disetel bersama-sama
    #: lewat `masuk.nonaktifkan`; keputusan "boleh masuk?" membaca keduanya.
    status: Mapped[str] = mapped_column(String(20), default=AKTIF, nullable=False)
    #: pribadi | bersama — umur sesi menurut jenis perangkat (lihat `mode_bawaan`).
    mode_perangkat: Mapped[str] = mapped_column(String(10), default=BERSAMA, nullable=False)
    harus_ganti_sandi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    terakhir_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Ikut di dalam token; naik saat keluar-semua, ganti/reset sandi, ganti
    #: peran, dan penonaktifan → semua token lama berhenti berlaku.
    token_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def peran(self) -> str:
        return self.user.role if self.user else ""

    @property
    def nama(self) -> str:
        return self.user.nama if self.user else self.username

    @property
    def is_admin(self) -> bool:
        return P.admin_keatas(self.peran)

    @property
    def is_super(self) -> bool:
        return P.super_saja(self.peran)

    @property
    def is_staff(self) -> bool:
        return P.staf_keatas(self.peran)

    @property
    def sesi_pendek(self) -> bool:
        return self.mode_perangkat == BERSAMA

    @property
    def aktif(self) -> bool:
        """Saklar gabungan: akun DAN orangnya aktif."""
        return (self.status == AKTIF and self.user is not None
                and (self.user.status or "").lower() == AKTIF)


def mode_bawaan(peran: str | None) -> str:
    """Operator → perangkat gudang bersama (sesi pendek); selebihnya pribadi."""
    return BERSAMA if P.operator_saja(peran) else PRIBADI
