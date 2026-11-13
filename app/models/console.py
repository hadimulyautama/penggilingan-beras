"""Sesi Console terpisah; tidak mengubah sesi akun aplikasi harian."""
from datetime import datetime
from sqlalchemy import Boolean,DateTime,ForeignKey,String,func,false
from sqlalchemy.orm import Mapped,mapped_column
from app.database import Base


class SesiConsole(Base):
    __tablename__='hmu_console_sessions'
    id:Mapped[int]=mapped_column(primary_key=True)
    akun_id:Mapped[int]=mapped_column(ForeignKey('produksi_akun.id',ondelete='RESTRICT'),nullable=False)
    versi:Mapped[int]=mapped_column(nullable=False)
    kode_hash:Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    tantangan:Mapped[str]=mapped_column(String(43),nullable=False)
    kode_sampai:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    token_hash:Mapped[str|None]=mapped_column(String(64),unique=True)
    sesi_sampai:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    ditukar_pada:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    dicabut:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default=false())
    dibuat_pada:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
