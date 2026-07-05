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


class FinishedGoodsStock(Base, TimestampMixin):
    """Stok barang jadi (dikemas): beras putih (grade), Beras B, broken/menir/
    reject kemasan. Masuk saat packing hasil produksi (atau retur kondisi baik).
    """

    __tablename__ = "finished_goods_stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_sku_id: Mapped[int] = mapped_column(
        ForeignKey("product_skus.id"), nullable=False
    )
    # NULL untuk byproduct kemasan & Beras B (tak punya standar mutu).
    rice_quality_standard_id: Mapped[int | None] = mapped_column(
        ForeignKey("rice_quality_standards.id")
    )
    # polishing / reject_reprocessing / retur
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    jumlah_karung: Mapped[int] = mapped_column(Integer, nullable=False)
    berat_total_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class ByproductStock(Base, TimestampMixin):
    """Stok hasil samping CURAH (hanya bekatul). Dijual per kg."""

    __tablename__ = "byproduct_stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    jenis_produk: Mapped[str] = mapped_column(String(20), nullable=False)
    # polishing / reject_reprocessing
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="tersedia")
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class ByproductPrice(Base, TimestampMixin):
    """Harga acuan byproduct (bekatul/broken/menir/reject) — untuk kredit HPP &
    penilaian stok. Baris terbaru per jenis = harga berlaku (histori terjaga)."""

    __tablename__ = "byproduct_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    harga_per_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class OutgoingRecord(Base, TimestampMixin):
    """Barang keluar / dikirim. Kode: OUT-YYYYMMDD-NN. Proses jual lengkap
    (pelanggan/faktur/piutang) ada di modul Penjualan; di sini = dispatch fisik."""

    __tablename__ = "outgoing_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    nama_pembeli: Mapped[str | None] = mapped_column(String(100))
    # truk_sendiri / ekspedisi / sewa / pickup
    metode: Mapped[str | None] = mapped_column(String(20))
    no_polisi: Mapped[str | None] = mapped_column(String(20))
    nama_ekspedisi: Mapped[str | None] = mapped_column(String(100))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    catatan: Mapped[str | None] = mapped_column(String(200))


class OutgoingItem(Base, TimestampMixin):
    """Item barang keluar. item_type: finished_goods (karung) / byproduct_curah
    (bekatul, kg) / pk_langsung (PK dari G1, kg→karung CEIL÷50). Harga OPSIONAL
    (penetapan harga penuh di modul Penjualan)."""

    __tablename__ = "outgoing_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    outgoing_record_id: Mapped[int] = mapped_column(
        ForeignKey("outgoing_records.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_sku_id: Mapped[int | None] = mapped_column(ForeignKey("product_skus.id"))
    rice_quality_standard_id: Mapped[int | None] = mapped_column(
        ForeignKey("rice_quality_standards.id")
    )
    jenis_byproduct: Mapped[str | None] = mapped_column(String(20))
    milling_process_id: Mapped[int | None] = mapped_column(ForeignKey("milling_process.id"))
    jumlah_karung: Mapped[int | None] = mapped_column(Integer)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    harga_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_harga: Mapped[float | None] = mapped_column(Numeric(16, 2))
