"""Permintaan operator Gudang 2 atas lot PK Gudang 1 — niat, bukan perpindahan."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

#: Status permintaan, dan hanya empat ini (CHECK di migrasi 0055).
TERBUKA, SELESAI, DITOLAK, GUGUR = "terbuka", "selesai", "ditolak", "gugur"


class PermintaanPk(Base, TimestampMixin):
    """Operator Gudang 2 meminta satu lot PK Gudang 1 dipindah kepadanya.

    Yang dicatat PERMINTAAN, bukan izin: `peran.can_transfer_pk` tidak berubah,
    dan yang memindahkan tetap Admin (keputusan pemilik 24 September 2026).

    Berdiri sendiri, TIDAK menumpang `peristiwa`/`proyeksi_*`: buku besar itu
    mencatat apa yang TERJADI pada barang, sedangkan baris di sini adalah niat
    yang bisa ditolak dan bisa gugur. Menumpangkannya ke sana berarti buku besar
    yang memuat baris yang tak pernah menggerakkan satu kilo pun.

    Satu yang TERBUKA per lot, dijaga indeks parsial `uq_permintaan_pk_terbuka`
    di basis data — bukan oleh layar, sebab layar tak bisa menjaga dua
    permintaan yang tiba pada detik yang sama.
    """

    __tablename__ = "permintaan_pk"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan pada
        # `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_permintaan_pk_proses", "milling_process_id"),
        Index("ix_permintaan_pk_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    diminta_oleh: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    waktu_minta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: terbuka / selesai / ditolak / gugur
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=TERBUKA)
    ditutup_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_tutup: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Kenapa ditutup. WAJIB saat ditolak (CHECK di migrasi): permintaan yang
    #: lenyap tanpa kabar membuat orang menekannya lagi.
    sebab: Mapped[str | None] = mapped_column(Text)
