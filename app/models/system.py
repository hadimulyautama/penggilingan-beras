"""Sistem pendukung: activity_logs (audit trail), notifications."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivityLog(Base):
    """Audit trail SEMUA perubahan — transaksi DAN master data (soft delete)."""

    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # INSERT / UPDATE / DELETE
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_perubahan: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    alasan_perubahan: Mapped[str | None] = mapped_column(Text)

    # ── Tag aksi: APA yang dikerjakan, disebut saat mengerjakannya ──
    #
    # Pembatalan dulu MENEBAK maksud sebuah catatan dari nama tabel, aksi, dan
    # nama kolomnya. Tebakan itu salah pada kasus yang paling mudah keliru:
    # "ubah target kadar air" dan "gabungkan batch ke lot" sama-sama UPDATE
    # pada `drying_lots`, jadi keduanya jatuh ke penangan yang sama — dan
    # membatalkan perubahan target justru MENGELUARKAN gabah dari lot yang
    # sedang dikeringkan.
    #
    # Boleh kosong: baris lama tak punya tag, dan pembatalannya jatuh ke
    # tebakan lama. Yang baru menyebut maksudnya sendiri.
    aksi: Mapped[str | None] = mapped_column(String(40), index=True)

    # ── Sudah dibatalkan? ──
    #
    # Pembatalan dulu MENGHAPUS baris ini, melanggar ARSITEKTUR §6: jejak audit
    # bersifat tambah-saja. Ia satu-satunya catatan siapa mengerjakan apa, dan
    # menghapusnya membuang bukti persis pada saat bukti itu dicari.
    #
    # Ditandai, bukan dihapus — dan penandanya juga yang mencegah pembatalan
    # ganda.
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dibatalkan_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Notification(Base):
    """Notifikasi otomatis 🔴🟡🟢. Eskalasi 24 jam ke admin. Laporan harian 21:00."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipe: Mapped[str] = mapped_column(String(50), nullable=False)
    record_id: Mapped[int | None] = mapped_column(Integer)
    table_name: Mapped[str | None] = mapped_column(String(64))
    # admin / staff / operator
    target_role: Mapped[str | None] = mapped_column(String(20))
    pesan: Mapped[str] = mapped_column(Text, nullable=False)
    # merah / kuning / hijau
    prioritas: Mapped[str] = mapped_column(String(10), default="kuning")
    # baru / dibaca / selesai
    status: Mapped[str] = mapped_column(String(20), default="baru")
    eskalasi_target: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    eskalasi_jam: Mapped[int] = mapped_column(Integer, default=24)
    # belum / sudah
    status_eskalasi: Mapped[str] = mapped_column(String(20), default="belum")
    waktu_eskalasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SetelanPabrik(Base):
    """Setelan yang berubah di lapangan — kunci & nilai.

    Bukan satu kolom per setelan: setelan bertambah lebih sering daripada
    migrasi ditulis, dan tabel yang menuntut migrasi tiap kali setelan
    bertambah akan berhenti dipakai — lalu angkanya kembali ditanam di kode,
    tempat yang hanya bisa diubah oleh yang menulis kodenya.
    """

    __tablename__ = "setelan_pabrik"

    kunci: Mapped[str] = mapped_column(String(64), primary_key=True)
    nilai: Mapped[str] = mapped_column(Text, nullable=False)
    diubah_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KodeUrut(Base):
    """Penghitung nomor harian per awalan kode — GB, PGR, LOT, TRF, …

    Nomor dulu dihitung `SELECT count(*) … + 1` atas tabel yang bersangkutan.
    Dua hal salah di situ, dan keduanya sudah terbukti:

    **Undo menghapus baris.** Sesudah Budi membatalkan GB-01, hitungannya
    kembali nol, jadi truk berikutnya menghitung GB-02 — yang sudah ada — lalu
    ditolak basis data. Dan tetap ditolak sepanjang hari: tiap percobaan
    menghitung angka yang sama. Operator membaca "Tiket timbang ini sudah
    ditautkan ke batch lain", pesan yang tak menyebut sebabnya sama sekali.

    **Dua operator bersamaan.** Keduanya menghitung angka yang sama sebelum
    salah satunya sempat menyimpan.

    Diambil dengan satu `INSERT … ON CONFLICT DO UPDATE … RETURNING`, di
    transaksi yang sama dengan penyisipan barisnya. Barisnya hanya bertambah.

    **Nomor boleh melompat.** Sesudah pembatalan, nomor yang terpakai tak
    diterbitkan ulang — GB-01 dibatalkan, truk berikutnya tetap GB-02. Itu
    disengaja: nomor yang muncul dua kali di buku dan di surat jalan lebih
    membingungkan daripada nomor yang bolong.
    """

    __tablename__ = "kode_urut"

    awalan: Mapped[str] = mapped_column(String(8), primary_key=True)
    tanggal: Mapped[date] = mapped_column(Date, primary_key=True)
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
