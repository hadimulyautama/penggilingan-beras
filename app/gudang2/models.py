"""Gudang 2 (Penyosohan) — PK masuk, intake ke silo/tumpukan, pindah tumpukan→silo.

Silo G2 = KOLAM CAMPURAN (boleh banyak sumber), beda dgn G1 (1 silo = 1 lot).
Stok silo/tumpukan DITURUNKAN dari intake + pindah − terpakai (lihat services).
Acuan: LOGIKA_SILO_GUDANG2.md.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class PkPurchaseBatch(Base, TimestampMixin):
    """Pembelian PK dari luar (bukan transfer dari Gudang 1). Kode: PKB-YYYYMMDD-NN."""

    __tablename__ = "pk_purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_batch: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    berat_total_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    no_polisi_truk: Mapped[str | None] = mapped_column(String(20))
    kadar_air_awal_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    tanggal_pembelian: Mapped[date] = mapped_column(Date, nullable=False)
    waktu_pembelian: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # baru / diterima / ditolak / di_silo / disosoh
    status_batch: Mapped[str] = mapped_column(String(20), default="baru")
    flag_unverified: Mapped[bool] = mapped_column(Boolean, default=True)

    supplier: Mapped["Supplier"] = relationship()  # noqa: F821
    verification: Mapped["PkPurchaseVerification | None"] = relationship(
        back_populates="batch", uselist=False
    )


class PkPurchaseVerification(Base, TimestampMixin):
    """QC + harga PK luar (staff/admin). QC menentukan terima/tolak + potongan."""

    __tablename__ = "pk_purchase_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    pk_purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("pk_purchase_batches.id"), unique=True, nullable=False
    )
    # QC
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    # terima / tolak
    keputusan: Mapped[str | None] = mapped_column(String(10))
    potongan_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    potongan_alasan: Mapped[str | None] = mapped_column(String(120))
    # Harga
    harga_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_biaya: Mapped[float | None] = mapped_column(Numeric(16, 2))
    # per_kg / total
    metode_harga: Mapped[str | None] = mapped_column(String(10))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")

    batch: Mapped["PkPurchaseBatch"] = relationship(back_populates="verification")


class PkGudang2Intake(Base, TimestampMixin):
    """Setiap PK yang MASUK ke Gudang 2 — dari beli luar atau transfer G1.

    tujuan: silo_a / silo_b / ditumpuk. silo_id NULL bila ditumpuk.
    Membawa snapshot HPP/kg (flag_hpp_belum_tersedia bila milling G1 belum verif).
    """

    __tablename__ = "pk_gudang2_intakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # beli_luar / transfer_internal
    sumber_tipe: Mapped[str] = mapped_column(String(20), nullable=False)
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pk_purchase_batches.id")
    )
    internal_transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("internal_transfers.id")
    )
    # silo_a / silo_b / ditumpuk
    tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    flag_hpp_belum_tersedia: Mapped[bool] = mapped_column(Boolean, default=True)
    tanggal_masuk: Mapped[date] = mapped_column(Date, nullable=False)
    waktu_masuk: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PkTumpukanToSilo(Base, TimestampMixin):
    """Pemindahan PK dari tumpukan ke silo (khusus Operator Gudang 2, admin fallback).

    Bisa parsial (tidak harus semua tumpukan sekaligus). Kode: PTS-YYYYMMDD-NN.
    """

    __tablename__ = "pk_tumpukan_to_silo"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    pk_gudang2_intake_id: Mapped[int] = mapped_column(
        ForeignKey("pk_gudang2_intakes.id"), nullable=False
    )
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PolishingProcess(Base, TimestampMixin):
    """Proses penyosohan (PK silo → beras putih). Kode: POL-YYYYMMDD-NN.

    Bahan WAJIB dari silo (bukan tumpukan). 1-2 hari = 1 proses.
    """

    __tablename__ = "polishing_process"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_proses: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    waktu_mulai: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    waktu_selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PolishingSiloUsage(Base, TimestampMixin):
    """Pemakaian silo per proses penyosohan.

    berat_awal_kg: snapshot OTOMATIS saat proses mulai (stok silo saat itu).
    berat_akhir_kg: input MANUAL operator saat selesai.
    berat_terpakai_kg: computed = berat_awal − berat_akhir (diisi saat selesai).
    """

    __tablename__ = "polishing_silo_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    polishing_process_id: Mapped[int] = mapped_column(
        ForeignKey("polishing_process.id"), nullable=False
    )
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_awal_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    berat_akhir_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    berat_terpakai_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))


class PolishingOutputLog(Base):
    """Log hasil penyosohan (KUMULATIF — ambil baris TERBARU per jenis).

    jenis: grade beras (sayur/medium/medsuper/premium/beras_b) ATAU hasil
    samping (menir/broken/bekatul/reject). berat_kg = kumulatif total.
    """

    __tablename__ = "polishing_output_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    polishing_process_id: Mapped[int] = mapped_column(
        ForeignKey("polishing_process.id"), nullable=False
    )
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    waktu_update: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
