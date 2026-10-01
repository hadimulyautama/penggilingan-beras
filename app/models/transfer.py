"""Transfer internal Gudang 1 → Gudang 2 (PK siap transfer)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class InternalTransfer(Base, TimestampMixin):
    """Transfer PK dari Gudang 1 ke Gudang 2. Dibuat staff/admin.

    Kode: TRF-YYYYMMDD-NN. Tidak pakai kendaraan (tanpa plat).
    """

    __tablename__ = "internal_transfers"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_internal_transfers_proses", "milling_process_id", "status"),
        Index("ix_internal_transfers_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_transfer: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    #: JENIS tempatnya: `silo` atau `ditumpuk`. Silo MANA ada di `silo_id`.
    #:
    #: Baris lama menyimpan `silo_a`/`silo_b` — dua nama silo yang diketik ke
    #: dalam kosakata datanya sendiri. Kosakata seperti itu tak bisa tumbuh:
    #: silo Gudang 2 ketiga tak punya kata, jadi ia ada di master, tampil di
    #: borang, dan tak bisa menerima satu kilogram pun. Sejak 24 September 2026
    #: yang disimpan JENIS tempatnya, dan identitas silonya jadi rujukan.
    #: Baris lama tetap terbaca: identitasnya dibaca dari `silo_id` yang diisi
    #: migrasi 0057, bukan dari kata itu.
    lokasi_tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Silo tujuan di Gudang 2. NULL berarti ditumpuk di lantai.
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    # Snapshot HPP per kg PK saat transfer (bila milling sudah diverifikasi).
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # terkirim / dibatalkan
    status: Mapped[str] = mapped_column(String(20), default="terkirim")
    #: Peristiwa `pk_dipindah_g1g2` yang melahirkan baris ini (Tahap 3, aksi
    #: keempat). Baris ini cermin yang TIDAK dihapus saat dibatalkan.
    peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Pesanan jasa yang memiliki PK yang dipindah ini. NULL = milik pabrik.
    #:
    #: DISALIN dari `milling_process.jasa_id` saat transfer dibuat, bukan dibaca
    #: ulang lewat lotnya: kalau pemiliknya dibaca menyusul, baris ini kehilangan
    #: artinya pada hari lotnya dikoreksi — dan yang dipindahkan sudah berpindah.
    #: Tanpa kolom ini, PK pelanggan berubah jadi PK pabrik tepat di perbatasan
    #: dua gudang, tanpa satu pun galat.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))
