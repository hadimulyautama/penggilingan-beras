"""Gudang 1 — Produksi (Fase 1): pembelian gabah, pengeringan, silo."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class PurchaseBatch(Base, TimestampMixin):
    """Pembelian gabah per batch. 1 truk = 1 batch. Maks 3 batch/hari.

    Kode: GB-YYYYMMDD-NN
    """

    __tablename__ = "purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_batch: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False
    )
    # Kosong = "menunggu bobot" (referensi bobot ada di tiket timbang; disinkron otomatis).
    berat_total_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    no_polisi_truk: Mapped[str | None] = mapped_column(String(20))
    # basah / kering
    kondisi_gabah: Mapped[str] = mapped_column(String(10), nullable=False)
    kadar_air_awal_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    tanggal_pembelian: Mapped[datetime] = mapped_column(Date, nullable=False)
    waktu_pembelian: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # baru / dikeringkan / di_silo / digiling / selesai
    status_batch: Mapped[str] = mapped_column(String(20), default="baru")
    #: Mesin tempat gabah ini MENUNGGU, sebelum lotnya terbentuk.
    #:
    #: Berarti hanya pada satu keadaan singkat: sejak masuk mesin sampai
    #: "mulai pengeringan" membentuk lot. Setelah itu yang menyimpan mesinnya
    #: adalah `DryingLot.dryer_id` dan kolom ini dikosongkan lagi — supaya
    #: tidak ada dua tempat yang menyebut mesin untuk gabah yang sama, lalu
    #: suatu hari berbeda.
    dryer_id: Mapped[int | None] = mapped_column(ForeignKey("dryers.id"), index=True)
    flag_unverified: Mapped[bool] = mapped_column(Boolean, default=True)
    # ── Tautan ke timbangan (shared DB). 1 tiket timbang = maks 1 batch. ──
    # berat_total_kg/supplier/no_polisi diturunkan dari transaksi timbang; operator
    # tak input lagi. sumber_berat: 'nota' (berat_acuan_kg) | 'timbangan' (netto real)
    # | 'manual' (tanpa jembatan). HPP: pakai nota bila ada, selain itu real.
    # Tabel timbangan_transaksi dimiliki repo timbangan (shared DB) — TAK ada di metadata
    # app ini, jadi FK cukup di level DB (migrasi 0027). Di ORM: kolom Integer + unique.
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(unique=True)
    sumber_berat: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")

    supplier: Mapped["Supplier"] = relationship()  # noqa: F821
    verification: Mapped["PurchaseBatchVerification | None"] = relationship(
        back_populates="batch", uselist=False
    )


class PurchaseBatchVerification(Base, TimestampMixin):
    """Verifikasi harga gabah oleh staff/admin. Proses tidak ditahan."""

    __tablename__ = "purchase_batch_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_batches.id"), unique=True, nullable=False
    )
    harga_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_biaya: Mapped[float | None] = mapped_column(Numeric(16, 2))
    # per_kg / total
    metode_harga: Mapped[str | None] = mapped_column(String(10))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # menunggu / terverifikasi
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")

    batch: Mapped[PurchaseBatch] = relationship(back_populates="verification")


class DryingLot(Base, TimestampMixin):
    """Lot pengeringan gabungan 2-3 batch. Tidak boleh campur basah & kering.

    Kode: LOT-YYYYMMDD-NN
    """

    __tablename__ = "drying_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_lot: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    dryer_id: Mapped[int | None] = mapped_column(ForeignKey("dryers.id"))
    waktu_mulai_pengeringan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    waktu_selesai_pengeringan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Fase pendinginan (di dryer): mulai OTOMATIS saat pengeringan selesai,
    # selesai OTOMATIS saat gabah dipindah ke silo.
    waktu_mulai_pendinginan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    waktu_selesai_pendinginan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    lot_batches: Mapped[list["DryingLotBatch"]] = relationship(
        back_populates="drying_lot"
    )
    moisture_logs: Mapped[list["DryingMoistureLog"]] = relationship(
        back_populates="drying_lot"
    )


class DryingLotBatch(Base):
    """Junction lot <-> batch. Validasi kondisi gabah harus sama (di service)."""

    __tablename__ = "drying_lot_batches"
    __table_args__ = (
        UniqueConstraint("drying_lot_id", "purchase_batch_id", name="uq_lot_batch"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int] = mapped_column(
        ForeignKey("drying_lots.id"), nullable=False
    )
    purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_batches.id"), nullable=False
    )

    drying_lot: Mapped[DryingLot] = relationship(back_populates="lot_batches")
    batch: Mapped[PurchaseBatch] = relationship()


class DryingMoistureLog(Base):
    """Log kadar air, wajib minimal tiap 5 jam. Notifikasi jika terlambat."""

    __tablename__ = "drying_moisture_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int] = mapped_column(
        ForeignKey("drying_lots.id"), nullable=False
    )
    waktu_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    kadar_air_indikator: Mapped[float | None] = mapped_column(Numeric(5, 2))
    kadar_air_tes_manual: Mapped[float | None] = mapped_column(Numeric(5, 2))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    drying_lot: Mapped[DryingLot] = relationship(back_populates="moisture_logs")


class DryingCoolingLog(Base):
    """Log pendinginan gabah — tetap di dryer, hanya sirkulasi udara.

    Bukan proses berpindah / berprogres; sekadar catatan timestamp + catatan.
    """

    __tablename__ = "drying_cooling_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int] = mapped_column(
        ForeignKey("drying_lots.id"), nullable=False
    )
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    catatan: Mapped[str | None] = mapped_column(String(255))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class SiloMovingLog(Base):
    """Log proses pemindahan gabah dari dryer ke silo (butuh waktu).

    Sekadar catatan kondisional (mulai/selesai). State sesungguhnya (gabah di
    silo, dryer kosong) ditangani oleh silo_storage.
    """

    __tablename__ = "silo_moving_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    # mulai / selesai
    tipe: Mapped[str] = mapped_column(String(10), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    catatan: Mapped[str | None] = mapped_column(String(255))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class SiloStorage(Base, TimestampMixin):
    """Penyimpanan gabah kering di silo. 1 silo = 1 lot sekaligus.

    Silo dianggap kosong saat milling selesai (bukan saat gabah keluar fisik).
    """

    __tablename__ = "silo_storage"

    id: Mapped[int] = mapped_column(primary_key=True)
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    # dari_pengeringan / langsung_kering
    tipe_masuk: Mapped[str] = mapped_column(String(20), nullable=False)
    tanggal_masuk: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tanggal_keluar: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # terisi / kosong
    status: Mapped[str] = mapped_column(String(20), default="terisi")
