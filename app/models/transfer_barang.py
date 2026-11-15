"""Transfer lokasi barang. Kepemilikan sumber tidak pernah diganti.

Permintaan/persetujuan menyimpan jumlah rencana. Fakta perpindahan dan
koreksinya berdiri sendiri; stok tetap berada di tabel sumber inventory.
"""
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, TimestampMixin


class PermintaanTransferBarang(Base, TimestampMixin):
    __tablename__ = 'permintaan_transfer_barang'
    __table_args__ = (
        Index('ix_permintaan_transfer_barang_sumber','sumber_jenis','sumber_id','status'),
        CheckConstraint("status IN ('diminta','disetujui','dikirim','selesai','ditolak','gugur')", name='ck_permintaan_transfer_barang_status'),
        CheckConstraint('jumlah_minta > 0 AND jumlah_setuju >= 0', name='ck_permintaan_transfer_barang_jumlah'),
        CheckConstraint('asal_id <> tujuan_id', name='ck_permintaan_transfer_barang_lokasi'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sumber_jenis: Mapped[str] = mapped_column(String(24), nullable=False)
    sumber_id: Mapped[str] = mapped_column(String(100), nullable=False)
    asal_id: Mapped[int] = mapped_column(ForeignKey('warehouses.id'), nullable=False, index=True)
    tujuan_id: Mapped[int] = mapped_column(ForeignKey('warehouses.id'), nullable=False, index=True)
    sumber: Mapped[dict] = mapped_column(JSON, nullable=False)
    satuan: Mapped[str] = mapped_column(String(12), nullable=False)
    jumlah_minta: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    jumlah_setuju: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='diminta', index=True)
    diminta_oleh: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    disetujui_oleh: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    waktu_minta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    waktu_setuju: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ditutup: Mapped[bool] = mapped_column(default=False, nullable=False)
    alasan: Mapped[str | None] = mapped_column(Text)
    kunci: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    sidik: Mapped[str] = mapped_column(String(64), nullable=False)


class TransferBarang(Base, TimestampMixin):
    __tablename__ = 'transfer_barang'
    __table_args__ = (CheckConstraint("status IN ('selesai','dibatalkan')", name='ck_transfer_barang_status'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    pengiriman_pk_id: Mapped[int | None] = mapped_column(ForeignKey('pengiriman_pk.id'), unique=True)
    asal_id: Mapped[int] = mapped_column(ForeignKey('warehouses.id'), nullable=False, index=True)
    tujuan_id: Mapped[int] = mapped_column(ForeignKey('warehouses.id'), nullable=False, index=True)
    dibuat_oleh: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='selesai')
    kunci: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    sidik: Mapped[str] = mapped_column(String(64), nullable=False)


class TransferBarangItem(Base):
    __tablename__ = 'transfer_barang_items'
    __table_args__ = (
        UniqueConstraint('transfer_id', 'permintaan_id', name='uq_transfer_barang_permintaan'),
        CheckConstraint('jumlah >= 0 AND (berat_kg IS NULL OR berat_kg >= 0)', name='ck_transfer_barang_item_jumlah'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey('transfer_barang.id'), nullable=False, index=True)
    permintaan_id: Mapped[int] = mapped_column(ForeignKey('permintaan_transfer_barang.id'), nullable=False, index=True)
    jumlah: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    berat_kg: Mapped[float | None] = mapped_column(Numeric(14, 2))
    dampak: Mapped[dict] = mapped_column(JSON, nullable=False)
