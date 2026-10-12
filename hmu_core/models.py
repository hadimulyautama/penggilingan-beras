"""Model master BERSAMA: identitas, lokasi, mutu, merek, dan kemasan.

Satu sumber kebenaran untuk SEMUA sistem (produksi, kantor, timbangan) via submodule `core`.
Diekstrak dari app/models/master.py — **skema HARUS identik dengan DB live** (jangan ubah
kolom tanpa migrasi). Gudang/silo/dryer dan master mutu/merek/kemasan dipakai
lintas aplikasi. Supplier/pelanggan dijembatani ke Kledo via kledo_contact_id.

Tabel mutu, merek, jenis kemasan, dan ukuran sudah dimiliki migrasi aplikasi
Operasional. Definisi ORM dipusatkan di paket ini; rantai migrasi Operasional
tetap mengelola tabelnya, sedangkan aplikasi lain hanya mereferensikannya.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, Text, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hmu_core.base import Base, TimestampMixin


class RiceQualityStandard(Base, TimestampMixin):
    """Nilai master untuk atribut kualitas Beras Putih."""

    __tablename__ = "rice_quality_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class Brand(Base, TimestampMixin):
    """Master merek yang dipakai identitas produk dan spesifikasi kemasan."""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    tipe: Mapped[str] = mapped_column(String(10), default="house")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PackagingMaterial(Base, TimestampMixin):
    """Master jenis/bahan karung atau kemasan."""

    __tablename__ = "packaging_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class PackageSize(Base, TimestampMixin):
    """Ukuran nominal kemasan dalam kilogram."""

    __tablename__ = "package_sizes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ukuran_kg: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


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
    # `unique=True` SAJA. Menambahkan `index=True` di sampingnya membuat
    # SQLAlchemy mengharapkan indeks unik bernama `ix_users_telegram_user_id`,
    # sementara basis data punya constraint `users_telegram_user_id_key` —
    # dua nama untuk satu benda, dan autogenerate mengusulkan menukar
    # keduanya tiap kali dijalankan. Constraint unik sudah berindeks.
    # Temuan QA X-19.
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
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

    __table_args__ = (
        # ── Satu nama, satu baris — selama ia belum dihapus ──
        #
        # Tiga penulis menyentuh tabel ini dan tak satu pun tahu tentang yang
        # lain; ketiganya mencari-lalu-membuat, dan pencarian yang mendahului
        # pembuatan selalu bisa disalip. Dua baris bernama sama memecah
        # riwayat satu orang jadi dua. PARSIAL: yang sudah dihapus boleh
        # bernama sama, karena itulah gunanya soft delete. Temuan QA X-20.
        Index("uq_suppliers_nama_hidup", text("lower(nama_supplier)"),
              unique=True, postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_supplier: Mapped[str] = mapped_column(String(150), nullable=False)
    no_telfon: Mapped[str | None] = mapped_column(String(30))
    alamat: Mapped[str | None] = mapped_column(Text)
    # aktif / nonaktif
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    # `timezone=True`: kolom ini `timestamptz` di basis data, dan model
    # yang menyebutnya tanpa zona membuat bentuknya bergantung pada SIAPA
    # yang membangun database — migrasi (berzona) atau `create_all`
    # (tanpa zona). Temuan QA X-19.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # `timezone=True`: kolom ini `timestamptz` di basis data, dan model
    # yang menyebutnya tanpa zona membuat bentuknya bergantung pada SIAPA
    # yang membangun database — migrasi (berzona) atau `create_all`
    # (tanpa zona). Temuan QA X-19.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kledo_contact_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


class Silo(Base, TimestampMixin):
    """Wadah penyimpanan komoditas yang sama lintas aplikasi.

    Silo adalah wadah umum; isinya dapat berupa gabah, beras (termasuk PK),
    broken, menir, reject, atau bekatul. `jenis_isi` menyatakan jenis bahan
    yang ditetapkan untuk silo tertentu, bukan kelas silo yang berbeda.
    Nilai 'pk' tetap menjadi bawaan untuk kompatibilitas baris lama dan
    pembuatan silo Gudang 2.
    """

    __tablename__ = "silos"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    nama_silo: Mapped[str] = mapped_column(String(50), nullable=False)
    kapasitas_ton: Mapped[float | None] = mapped_column(Numeric(10, 2))
    # kosong / terisi
    status: Mapped[str] = mapped_column(String(20), default="kosong")
    # Jenis bahan (mis. gabah, pk, beras, broken, menir, reject, bekatul).
    jenis_isi: Mapped[str] = mapped_column(String(20), nullable=False, default="pk")

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


class Armada(Base, TimestampMixin):
    """Identitas kendaraan bersama lintas Timbangan dan Operasional.

    Nama tabel `timbangan_kendaraan` dipertahankan agar seluruh data kendaraan
    dan foreign key transaksi timbang yang sudah ada tetap utuh. Kepemilikan
    tabel beralih ke skema bersama; detail transaksi tetap milik Timbangan.
    """

    __tablename__ = "timbangan_kendaraan"

    id: Mapped[int] = mapped_column(primary_key=True)
    nomor_polisi: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    catatan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktif")
