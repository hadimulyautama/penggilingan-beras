"""Master data produk & kemasan (modul inventory). Migrasi 0009.

Acuan: LOGIKA_PRODUK_JADI_INVENTORY.md + MASTER_RULES_AND_LOGIC.md §15-16, §21.
- Standar mutu beras putih = 4 (Sayur/Medium/MedSuper/Premium); admin-only ubah.
- Merk: 7 house + Polos (merk milik pembeli = label bebas, bukan master).
- SKU (kategori×merk×karung×ukuran) dibuat OTOMATIS saat pertama dipakai.
- Kemasan: harga/lembar dilacak (untuk HPP kemasan rata-rata tertimbang).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class RiceQualityStandard(Base, TimestampMixin):
    """Standar mutu beras putih (4). Beras B TIDAK punya standar. Admin-only ubah."""

    __tablename__ = "rice_quality_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class Brand(Base, TimestampMixin):
    """Merk. tipe: house (milik sendiri) / polos (tanpa merk). Merk pembeli =
    label bebas di transaksi, bukan baris di sini."""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # house / polos
    tipe: Mapped[str] = mapped_column(String(10), default="house")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PackagingMaterial(Base, TimestampMixin):
    """Jenis karung/kemasan: biasa, laminasi, putih, polos, bekas, karung_pk."""

    __tablename__ = "packaging_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class PackageSize(Base, TimestampMixin):
    """Ukuran kemasan (kg): 5, 10, 25, 48, 50."""

    __tablename__ = "package_sizes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ukuran_kg: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductSku(Base, TimestampMixin):
    """SKU produk = kategori × merk × jenis karung × ukuran. Dibuat on-demand.

    kategori: beras_putih / beras_b / broken / menir / reject / pk.
    brand_id NULL untuk hasil samping (broken/menir/reject) & PK.
    """

    __tablename__ = "product_skus"

    id: Mapped[int] = mapped_column(primary_key=True)
    kategori: Mapped[str] = mapped_column(String(20), nullable=False)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    packaging_material_id: Mapped[int] = mapped_column(
        ForeignKey("packaging_materials.id"), nullable=False
    )
    package_size_id: Mapped[int] = mapped_column(
        ForeignKey("package_sizes.id"), nullable=False
    )
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class PackagingPurchase(Base, TimestampMixin):
    """Pembelian kemasan (karung). Kode: PKP-YYYYMMDD-NN. Harga/lembar utk HPP."""

    __tablename__ = "packaging_purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    packaging_material_id: Mapped[int] = mapped_column(
        ForeignKey("packaging_materials.id"), nullable=False
    )
    package_size_id: Mapped[int] = mapped_column(
        ForeignKey("package_sizes.id"), nullable=False
    )
    jumlah_lembar: Mapped[int] = mapped_column(Integer, nullable=False)
    harga_per_lembar: Mapped[float | None] = mapped_column(Numeric(12, 2))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PackagingLoss(Base, TimestampMixin):
    """Kehilangan/kerusakan kemasan (mengurangi stok karung)."""

    __tablename__ = "packaging_losses"

    id: Mapped[int] = mapped_column(primary_key=True)
    packaging_material_id: Mapped[int] = mapped_column(
        ForeignKey("packaging_materials.id"), nullable=False
    )
    package_size_id: Mapped[int] = mapped_column(
        ForeignKey("package_sizes.id"), nullable=False
    )
    jumlah_lembar: Mapped[int] = mapped_column(Integer, nullable=False)
    alasan: Mapped[str | None] = mapped_column(String(120))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
