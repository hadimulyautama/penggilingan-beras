"""Master data BERSAMA: users, suppliers, pelanggan, warehouses, silos, dryers.

Satu sumber kebenaran untuk SEMUA sistem (produksi, kantor, timbangan) via submodule `core`.
Diekstrak dari app/models/master.py — **skema HARUS identik dengan DB live** (jangan ubah
kolom tanpa migrasi core). Master fisik (warehouse/silo/dryer) + master kontak (supplier/
pelanggan, dijembatani ke Kledo via kledo_contact_id) + user (auth/RBAC).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hmu_core.base import Base, TimestampMixin


class Warehouse(Base, TimestampMixin):
    """Gudang 1 (Selepan, tumpuk PK maks 30t) & Gudang 2 (Penyosohan, maks 60t)."""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_gudang: Mapped[str] = mapped_column(String(100), nullable=False)
    alamat: Mapped[str | None] = mapped_column(Text)
    kapasitas_tumpuk_ton: Mapped[float | None] = mapped_column(Numeric(10, 2))
    kapasitas_tumpuk_pk_ton: Mapped[float | None] = mapped_column(Numeric(10, 2))

    silos: Mapped[list["Silo"]] = relationship(back_populates="warehouse")


class User(Base, TimestampMixin):
    """Pengguna sistem. Identifikasi runtime via telegram_user_id (dokumen asli WhatsApp)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    # admin / staff / operator
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    whatsapp_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    default_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    # full / operational
    access_level: Mapped[str] = mapped_column(String(20), default="operational")
    wa_broadcast_opt_in: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="aktif")

    default_warehouse: Mapped[Warehouse | None] = relationship()


class Supplier(Base, TimestampMixin):
    """Supplier gabah & beras PK (bisa sama). Soft delete via deleted_at.

    kledo_contact_id = jembatan ke kontak Kledo (sumber identitas supplier ke depan)."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_supplier: Mapped[str] = mapped_column(String(150), nullable=False)
    no_telfon: Mapped[str | None] = mapped_column(String(30))
    alamat: Mapped[str | None] = mapped_column(Text)
    # aktif / nonaktif
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    deleted_at: Mapped[datetime | None] = mapped_column()
    kledo_contact_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


class Pelanggan(Base, TimestampMixin):
    """Pembeli beras & hasil samping. Tabel TERSENDIRI (bukan kolom tipe pada suppliers):
    peran ditentukan PADA TRANSAKSI, bukan pada entitas. Rekap total = urusan Kledo."""

    __tablename__ = "pelanggan"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_pelanggan: Mapped[str] = mapped_column(String(150), nullable=False)
    no_telfon: Mapped[str | None] = mapped_column(String(30))
    alamat: Mapped[str | None] = mapped_column(Text)
    # aktif / nonaktif
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    deleted_at: Mapped[datetime | None] = mapped_column()
    kledo_contact_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


class Silo(Base, TimestampMixin):
    """Silo A & B per gudang. G1: khusus gabah kering. G2: kolam campuran PK."""

    __tablename__ = "silos"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    nama_silo: Mapped[str] = mapped_column(String(50), nullable=False)
    kapasitas_ton: Mapped[float | None] = mapped_column(Numeric(10, 2))
    # kosong / terisi
    status: Mapped[str] = mapped_column(String(20), default="kosong")

    warehouse: Mapped[Warehouse] = relationship(back_populates="silos")


class Dryer(Base, TimestampMixin):
    """Mesin pengering (oven/dryer) Gudang 1. Sumber daya berkapasitas."""

    __tablename__ = "dryers"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    kapasitas_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # aktif / rusak / maintenance
    status: Mapped[str] = mapped_column(String(20), default="aktif")
