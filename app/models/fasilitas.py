"""Master fasilitas; bukan ledger stok atau pengganti proses domain."""
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, TimestampMixin

class JenisProsesProduksi(Base, TimestampMixin):
    __tablename__ = "jenis_proses_produksi"
    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(40), unique=True)
    nama: Mapped[str] = mapped_column(String(100))
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    versi: Mapped[int] = mapped_column(Integer, default=1)

class LiniProduksi(Base, TimestampMixin):
    __tablename__ = "lini_produksi"
    __table_args__ = (UniqueConstraint("warehouse_id", "kode", name="uq_lini_gudang_kode"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(40))
    nama: Mapped[str] = mapped_column(String(100))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    jenis_proses_id: Mapped[int] = mapped_column(ForeignKey("jenis_proses_produksi.id"))
    dryer_id: Mapped[int | None] = mapped_column(ForeignKey("dryers.id"), unique=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    versi: Mapped[int] = mapped_column(Integer, default=1)

class AuditFasilitas(Base, TimestampMixin):
    __tablename__ = "audit_fasilitas"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    objek: Mapped[str] = mapped_column(String(40))
    objek_id: Mapped[int] = mapped_column(Integer)
    sebelum: Mapped[dict | None] = mapped_column(JSON)
    sesudah: Mapped[dict] = mapped_column(JSON)
