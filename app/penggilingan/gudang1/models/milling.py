"""Gudang 1 — Proses Pecah Kulit (Milling) & buffer PK. Migrasi 0002."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    text,
    Index,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class MillingProcess(Base, TimestampMixin):
    """Proses pecah kulit per silo — gabah kering jadi PK. Kode lot giling:
    LOT-YYYYMMDD-NN (dulu MIL-; "lot" milik giling sejak pengeringan dilepas
    jadi PGR-, karena lot yang sesungguhnya terbentuk saat giling dimulai)."""

    __tablename__ = "milling_process"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("uq_milling_process_silo_proses", "silo_id", unique=True,
              postgresql_where=text(
                  "silo_id IS NOT NULL AND status = 'proses'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_proses: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    silo_storage_id: Mapped[int | None] = mapped_column(ForeignKey("silo_storage.id"))
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    berat_gabah_masuk_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: False bila ada bahan yang masih perkiraan / belum diketahui saat giling
    #: dimulai (QA P6-03). Poller membetulkan `berat_gabah_masuk_kg` proses
    #: seperti ini WALAU sudah selesai, dan rekonsiliasi menyebutnya sampai
    #: final. Verifikasi output menunggu kolom ini true.
    bobot_masuk_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                                    server_default=text("true"))
    waktu_mulai: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    waktu_selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingProgressLog(Base):
    """Monitoring berat kumulatif PK yang keluar (informatif)."""

    __tablename__ = "milling_progress_logs"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_milling_progress_proses", "milling_process_id",
              text("waktu_update DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    waktu_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    berat_kumulatif_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingQcLog(Base):
    """QC hasil PK oleh staff/admin (min. 1x per lot)."""

    __tablename__ = "milling_qc_logs"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_milling_qc_proses", "milling_process_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    susut_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    # KS / KL / MIX
    kondisi: Mapped[str | None] = mapped_column(String(10))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingProcessVerification(Base, TimestampMixin):
    """Verifikasi berat output PK final oleh staff/admin."""

    __tablename__ = "milling_process_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), unique=True, nullable=False
    )
    berat_output_final_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")


class MillingProcessSource(Base):
    """Isi satu proses giling — satu baris per sumber yang ikut digiling.

    Memisahkan dua arti yang dulu dipaksa jadi satu tabel: `DryingLot` berarti
    satu PROSES PENGERINGAN (dryer, kadar air, pendinginan), sedangkan proses
    giling berarti APA YANG DIGILING BERSAMA. Selama satu silo hanya boleh
    berisi satu hal, keduanya kebetulan sama; begitu silo boleh dicampur,
    penunjuk tunggal di `MillingProcess` akan memilih salah satu dan
    mengabaikan sisanya — gabahnya tergiling, tetapi tidak tercatat.

    `berat_kg` disalin saat giling dimulai, bukan dihitung ulang belakangan:
    isi silo berubah setelah itu, dan berapa yang MASUK ke mesin tidak boleh
    ikut berubah bersamanya.
    """

    __tablename__ = "milling_process_sources"
    # Satu baris silo tidak boleh masuk dua kali ke proses yang sama —
    # kalau bisa, beratnya terhitung ganda dan HPP-nya ikut salah.
    __table_args__ = (
        UniqueConstraint("milling_process_id", "silo_storage_id",
                         name="uq_mps_proses_silo"),
        # Dinamai apa adanya seperti di basis data. `index=True` polos membuat
        # SQLAlchemy mengharapkan nama bawaannya, dan autogenerate lalu
        # mengusulkan membuat indeks baru sambil menghapus yang lama — indeks
        # yang sama, dua nama. Temuan QA X-19.
        Index("ix_mps_proses", "milling_process_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id", ondelete="CASCADE"), nullable=False
    )
    silo_storage_id: Mapped[int] = mapped_column(
        ForeignKey("silo_storage.id"), nullable=False
    )
    #: Tepat satu dari dua ini terisi — sama seperti di `SiloStorage`.
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_batches.id"))
    #: NULL = bahan ini belum punya angka saat giling dimulai (truk belum
    #: ditimbang kedua, tanpa tara). Bukan 0 — CHECK berat_positif menolak
    #: nol, dan memang nol itu bohong. Diisi poller begitu timbangnya ada.
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
