"""Satu transfer membawa beberapa bagian permintaan PK; tiket hanya untuk perjalanan historis."""
from datetime import datetime
from sqlalchemy import Boolean, true, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, TimestampMixin

class PengirimanPk(Base, TimestampMixin):
    __tablename__='pengiriman_pk'
    __table_args__=(CheckConstraint("status IN ('dalam_perjalanan','menunggu_admin','selesai','dibatalkan')",name='ck_pengiriman_pk_status'),CheckConstraint("(pakai_kendaraan AND nomor_polisi IS NOT NULL AND nama_sopir IS NOT NULL) OR (NOT pakai_kendaraan AND nomor_polisi IS NULL AND nama_sopir IS NULL AND tiket_id IS NULL AND status IN ('selesai','dibatalkan'))",name='ck_pengiriman_pk_kendaraan'))
    id:Mapped[int]=mapped_column(primary_key=True)
    status:Mapped[str]=mapped_column(String(24),default='dalam_perjalanan',nullable=False)
    kunci:Mapped[str]=mapped_column(String(120),unique=True,nullable=False)
    sidik:Mapped[str]=mapped_column(String(64),nullable=False)
    asal_id:Mapped[int]=mapped_column(ForeignKey('warehouses.id'),nullable=False)
    tujuan_id:Mapped[int]=mapped_column(ForeignKey('warehouses.id'),nullable=False)
    silo_id:Mapped[int|None]=mapped_column(ForeignKey('silos.id'))
    jasa_id:Mapped[int|None]=mapped_column(ForeignKey('jasa.id'))
    pakai_kendaraan:Mapped[bool]=mapped_column(Boolean,default=True,server_default=true(),nullable=False)
    nomor_polisi:Mapped[str|None]=mapped_column(String(30))
    nama_sopir:Mapped[str|None]=mapped_column(String(100))
    dibuat_oleh:Mapped[int]=mapped_column(ForeignKey('users.id'),nullable=False)
    waktu:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    # Tabel tiket dimiliki TeraFlow; ID ini ditetapkan dari pembacaan tiket,
    # bukan diketik operator. Satu tiket hanya mengesahkan satu perjalanan.
    tiket_id:Mapped[int|None]=mapped_column(Integer,unique=True)
    bobot_timbang_kg:Mapped[float|None]=mapped_column(Numeric(14,4))
    selisih_kg:Mapped[float|None]=mapped_column(Numeric(14,4))
    alasan:Mapped[str|None]=mapped_column(Text)
    diputus_oleh:Mapped[int|None]=mapped_column(ForeignKey('users.id'))
    waktu_selesai:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class PengirimanPkItem(Base):
    __tablename__='pengiriman_pk_items'
    __table_args__=(UniqueConstraint('pengiriman_id','permintaan_id',name='uq_pengiriman_pk_permintaan'),CheckConstraint('berat_kg >= 0',name='ck_pengiriman_pk_item_positif'))
    id:Mapped[int]=mapped_column(primary_key=True)
    pengiriman_id:Mapped[int]=mapped_column(ForeignKey('pengiriman_pk.id'),index=True,nullable=False)
    permintaan_id:Mapped[int]=mapped_column(ForeignKey('permintaan_pk.id'),index=True,nullable=False)
    berat_kg:Mapped[float]=mapped_column(Numeric(12,2),nullable=False)
    internal_transfer_id:Mapped[int|None]=mapped_column(ForeignKey('internal_transfers.id'),unique=True)
