"""Permintaan operator Gudang 2 atas lot PK Gudang 1 — niat, bukan perpindahan."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

#: Keadaan permintaan — enam, dan CHECK-nya di migrasi 0058.
#:
#: Empat langkah, empat tangan (keputusan pemilik 25 September 2026):
#:   DIMINTA   operator Gudang 2 menekan "Minta lot ini"
#:   DISETUJUI admin menetapkan TUJUAN dan BOBOT
#:   DIKIRIM   operator Gudang 1 mengeksekusi — DI SINI BARANGNYA BERPINDAH
#:   SELESAI   admin menutup, dan boleh mengubah bobotnya
#: Dua jalan keluar yang lain: DITOLAK (sebab wajib) dan GUGUR (lot habis
#: lewat jalan lain).
DIMINTA, DISETUJUI, DIKIRIM = "diminta", "disetujui", "dikirim"
SELESAI, DITOLAK, GUGUR = "selesai", "ditolak", "gugur"

#: Yang masih BERJALAN — dipakai kartu, penggugur, dan indeks parsialnya.
#: Satu daftar, bukan tiga salinan: daftar yang disalin akan tertinggal di
#: salah satunya, dan yang tertinggal jadi satu-satunya pintu yang terbuka.
HIDUP = (DIMINTA, DISETUJUI, DIKIRIM)


class PermintaanPk(Base, TimestampMixin):
    """Operator Gudang 2 meminta satu lot PK Gudang 1 dipindah kepadanya.

    Yang dicatat PERMINTAAN, bukan izin — dan sejak 25 September 2026 ia sebuah
    PROSES, bukan pengingat: empat langkah di empat tangan (lihat daftar
    keadaan di atas). `peran.can_transfer_pk` TETAP tidak berubah; kemampuan
    baru operator Gudang 1 berpagar pada barisnya sendiri ("atas permintaan
    yang sudah disetujui"), bukan pada perannya. Melebarkan perannya berarti
    ia boleh memindahkan apa saja kapan saja — kebalikan dari yang diminta.

    Berdiri sendiri, TIDAK menumpang `peristiwa`/`proyeksi_*`: buku besar itu
    mencatat apa yang TERJADI pada barang, sedangkan baris di sini adalah niat
    yang bisa ditolak dan bisa gugur. Menumpangkannya ke sana berarti buku besar
    yang memuat baris yang tak pernah menggerakkan satu kilo pun.

    Satu yang BERJALAN per lot, dijaga indeks parsial `uq_permintaan_pk_hidup`
    di basis data — bukan oleh layar, sebab layar tak bisa menjaga dua
    permintaan yang tiba pada detik yang sama. Melebar ke ketiga keadaan
    berjalan 25 September 2026: indeks yang hanya menjaga keadaan pertama akan
    membiarkan lot yang sudah disetujui diminta lagi, dan dua permintaan
    berjalan atas satu lot berarti dua perpindahan atas PK yang sama.
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
    #: Lihat daftar keadaan di atas berkas ini.
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=DIMINTA)

    # ── 2 · ACC admin ──
    #: Jenis tempatnya di Gudang 2: `silo` atau `ditumpuk`; silo MANA di
    #: `silo_id`. Kosakata 25 September 2026 (migrasi 0057) — BUKAN
    #: `silo_a`/`silo_b`, yang justru dipensiunkan pagi itu juga.
    tujuan: Mapped[str | None] = mapped_column(String(12))
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    #: Bobot yang DISETUJUI admin — batas atas yang boleh dimuat Gudang 1.
    berat_setuju_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    disetujui_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_setuju: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── 3 · Eksekusi operator Gudang 1 ──
    #: Bobot yang BENAR-BENAR dimuat, menurut yang memuatnya. TIDAK PERNAH
    #: ditimpa saat admin menutup: kalau angka admin berbeda, selisih keduanya
    #: justru yang perlu bisa ditelusuri (keputusan pemilik).
    berat_kirim_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    dikirim_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_kirim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Perpindahan sungguhannya. Di sinilah niat bertemu barang — dan hanya di
    #: sini: tabel ini tetap TIDAK menumpang `peristiwa`/`proyeksi_*`.
    internal_transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("internal_transfers.id"))

    # ── 4 · Penutupan admin ──
    #: Angka yang BERLAKU. Bila beda dari `berat_kirim_kg`, perpindahannya
    #: dikoreksi lewat peristiwa lawan — bukan di-UPDATE di tempat.
    berat_final_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    ditutup_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_tutup: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Kenapa ditutup. WAJIB saat ditolak (CHECK di migrasi): permintaan yang
    #: lenyap tanpa kabar membuat orang menekannya lagi.
    sebab: Mapped[str | None] = mapped_column(Text)
