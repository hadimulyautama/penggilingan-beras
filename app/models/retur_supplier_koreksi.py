"""Tindakan sesudah keluar; angka awal dan mutasi awal tetap utuh."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger,Boolean,DateTime,ForeignKey,JSON,Numeric,String,Text,UniqueConstraint,Integer
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base


class ReturSupplierEfektif(Base):
    __tablename__='retur_supplier_efektif'
    retur_supplier_id:Mapped[int]=mapped_column(ForeignKey('retur_supplier.id'),primary_key=True)
    versi:Mapped[int]=mapped_column(default=0)
    keterangan:Mapped[str|None]=mapped_column(Text)
    dibatalkan:Mapped[bool]=mapped_column(Boolean,default=False)
    keberadaan:Mapped[str|None]=mapped_column(String(20))
    wajib_manual:Mapped[bool]=mapped_column(Boolean,default=False)
    dasar_besar:Mapped[dict|None]=mapped_column(JSON)


class ReturSupplierPerubahan(Base):
    __tablename__='retur_supplier_perubahan'
    __table_args__=(UniqueConstraint('retur_supplier_id','versi',name='uq_rsp_perubahan_versi'),)
    peristiwa_id:Mapped[int]=mapped_column(BigInteger().with_variant(Integer,'sqlite'),ForeignKey('peristiwa.id'),primary_key=True)
    retur_supplier_id:Mapped[int]=mapped_column(ForeignKey('retur_supplier.id'),index=True)
    versi:Mapped[int]=mapped_column()
    jenis:Mapped[str]=mapped_column(String(20))
    snapshot:Mapped[dict]=mapped_column(JSON)
    input_by:Mapped[int]=mapped_column(ForeignKey('users.id'))
    waktu:Mapped[datetime]=mapped_column(DateTime(timezone=True))


class ReturSupplierSelisih(Base):
    __tablename__='retur_supplier_selisih'
    peristiwa_id:Mapped[int]=mapped_column(ForeignKey('retur_supplier_perubahan.peristiwa_id'),primary_key=True)
    item_id:Mapped[int]=mapped_column(ForeignKey('retur_supplier_items.id'),primary_key=True,index=True)
    # Positif berarti tambahan keluar, negatif membetulkan keluar berlebih.
    bobot_kg:Mapped[Decimal]=mapped_column(Numeric(22,8))
    jumlah:Mapped[Decimal]=mapped_column(Numeric(14,2))


class ReturSupplierDrafKoreksi(Base):
    __tablename__='retur_supplier_draf_koreksi'
    kunci:Mapped[str]=mapped_column(String(64),primary_key=True)
    retur_supplier_id:Mapped[int]=mapped_column(ForeignKey('retur_supplier.id'),index=True)
    versi:Mapped[int]=mapped_column()
    snapshot:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(30))
    input_by:Mapped[int]=mapped_column(ForeignKey('users.id'))
    waktu:Mapped[datetime]=mapped_column(DateTime(timezone=True))
