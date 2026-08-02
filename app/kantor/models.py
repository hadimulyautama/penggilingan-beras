"""Model data domain Kantor AI.

Tabel fondasi lintas-peran:
  - Otak perusahaan   : SopDokumen, SopChunk
  - Guardrail/approval : AksiPending  (antrian aksi 🔴 propose→approve→execute)
  - Jejak audit        : KantorAuditLog
  - Aset               : Aset, KartuPemeliharaan

Semua timestamp timezone-aware (server_default now()). Konsisten dengan gaya
app/models/system.py. Prefix tabel 'kantor_' agar tak bentrok dgn domain pabrik.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ─────────────────────────── Otak perusahaan ───────────────────────────
class SopDokumen(Base):
    """Satu dokumen sumber pengetahuan (SOP, kebijakan, panduan, profil).

    Sumber bisa file repo, Google Drive, atau teks langsung. Isi mentah
    dipotong menjadi SopChunk untuk retrieval oleh peran.
    """

    __tablename__ = "kantor_sop_dokumen"

    id: Mapped[int] = mapped_column(primary_key=True)
    judul: Mapped[str] = mapped_column(String(255), nullable=False)
    # sop / kebijakan / panduan / profil / template / lainnya
    kategori: Mapped[str] = mapped_column(String(40), default="sop")
    # repo / gdrive / manual
    sumber: Mapped[str] = mapped_column(String(20), default="manual")
    # path repo, gdrive file id, atau null
    sumber_ref: Mapped[str | None] = mapped_column(String(512))
    # sha256 isi → deteksi perubahan agar tak re-ingest berulang
    konten_hash: Mapped[str | None] = mapped_column(String(64))
    # peran yang paling relevan (cfo/hrd/arsip/aset/umum), utk filter retrieval
    ranah: Mapped[str] = mapped_column(String(20), default="umum")
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SopChunk(Base):
    """Potongan teks dari SopDokumen — unit retrieval untuk konteks peran.

    Fase 0 memakai pencarian kata kunci (sederhana, tanpa infra vektor).
    Kolom `embedding` disiapkan untuk upgrade semantic search di fase lanjut
    (mis. pgvector) tanpa migrasi ulang skema besar.
    """

    __tablename__ = "kantor_sop_chunk"

    id: Mapped[int] = mapped_column(primary_key=True)
    dokumen_id: Mapped[int] = mapped_column(
        ForeignKey("kantor_sop_dokumen.id", ondelete="CASCADE"), nullable=False
    )
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    isi: Mapped[str] = mapped_column(Text, nullable=False)
    # disimpan sbg teks JSON bila/ketika embedding diaktifkan (fase lanjut)
    embedding: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ─────────────────────── Guardrail / antrian approval ───────────────────
class AksiPending(Base):
    """Aksi 🔴 konsekuensial yang menunggu persetujuan pemilik.

    Pola: agent PROPOSE aksi (deskripsi + payload deterministik) → pemilik
    APPROVE/TOLAK via Telegram → sistem EXECUTE payload apa adanya (tanpa
    re-reasoning LLM). Meniru pola undo.py: keputusan & eksekusi terpisah.
    """

    __tablename__ = "kantor_aksi_pending"

    id: Mapped[int] = mapped_column(primary_key=True)
    # peran pengusul: cfo/hrd/arsip/aset/advisor/kepala_staf
    peran: Mapped[str] = mapped_column(String(20), nullable=False)
    # jenis aksi: drive_move / drive_delete / email_send / dokumen_tulis / bayar_reminder ...
    jenis: Mapped[str] = mapped_column(String(40), nullable=False)
    # tier risiko: hijau/kuning/merah (merah = wajib approve)
    tier: Mapped[str] = mapped_column(String(10), default="merah")
    ringkasan: Mapped[str] = mapped_column(Text, nullable=False)
    # payload deterministik utk eksekutor (JSON sbg teks)
    payload: Mapped[str | None] = mapped_column(Text)
    # pending / disetujui / ditolak / dieksekusi / gagal / kedaluwarsa
    status: Mapped[str] = mapped_column(String(20), default="pending")
    diminta_oleh: Mapped[str | None] = mapped_column(String(60))  # trigger/scheduler/telegram
    diputus_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    hasil: Mapped[str | None] = mapped_column(Text)  # ringkasan hasil eksekusi/error
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    diputus_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kedaluwarsa_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─────────────────────────────── Audit ─────────────────────────────────
class KantorAuditLog(Base):
    """Jejak SEMUA aksi agent kantor (Drive/email/dokumen/keuangan/saran).

    Wajib untuk telusur & rollback. Berbeda dari activity_logs pabrik: fokus
    pada aksi agent lintas-sistem eksternal, bukan mutasi tabel DB internal.
    """

    __tablename__ = "kantor_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    peran: Mapped[str | None] = mapped_column(String(20))
    aksi: Mapped[str] = mapped_column(String(60), nullable=False)
    target: Mapped[str | None] = mapped_column(String(512))  # file id, email, dsb
    detail: Mapped[str | None] = mapped_column(Text)         # JSON teks
    # sukses / gagal / dry_run
    status: Mapped[str] = mapped_column(String(20), default="sukses")
    aksi_pending_id: Mapped[int | None] = mapped_column(
        ForeignKey("kantor_aksi_pending.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ─────────────────────────────── Aset ──────────────────────────────────
class Aset(Base):
    """Register aset perusahaan (mesin, kendaraan, alat, properti)."""

    __tablename__ = "kantor_aset"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(255), nullable=False)
    kategori: Mapped[str | None] = mapped_column(String(60))   # mesin/kendaraan/alat/properti
    lokasi: Mapped[str | None] = mapped_column(String(255))
    penanggung_jawab: Mapped[str | None] = mapped_column(String(120))
    tanggal_perolehan: Mapped[date | None] = mapped_column(Date)
    nilai_perolehan: Mapped[float | None] = mapped_column(Numeric(15, 2))
    # ── Lapisan akuntansi aset tetap (penyusutan) ──
    masa_manfaat_tahun: Mapped[int | None] = mapped_column(Integer)      # umur ekonomis
    metode_penyusutan: Mapped[str] = mapped_column(String(20), default="garis_lurus")
    nilai_residu: Mapped[float | None] = mapped_column(Numeric(15, 2))   # nilai sisa
    # aktif / perbaikan / nonaktif / dijual
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    catatan: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NomorDokumen(Base):
    """Register penomoran naskah dinas — SUMBER TUNGGAL nomor surat/dokumen.

    Menegakkan Pedoman Tata Naskah Dinas (PDM/TND/PT-HMU/01):
      - Surat  : NNN-KODE-PT-HMU-BULAN(Romawi)-TAHUN  (urut per-kode, reset tahunan)
      - Dokumen: JENIS/KODE/PT-HMU/NO

    `urut` unik per (jenis, kode, tahun) → cegah nomor ganda. Nomor batal diberi
    status 'batal' (bukan dihapus) agar urutan tetap tertelusuri.
    """

    __tablename__ = "kantor_nomor_dokumen"
    __table_args__ = (
        UniqueConstraint("jenis", "kode", "divisi", "tahun", "urut", name="uq_nomor_urut"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nomor_lengkap: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # surat / dokumen
    jenis: Mapped[str] = mapped_column(String(10), nullable=False, default="surat")
    kode: Mapped[str] = mapped_column(String(12), nullable=False)   # CSR, SK, ST...
    divisi: Mapped[str | None] = mapped_column(String(8))           # HRGA, KEU... (null utk dokumen)
    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    bulan: Mapped[int | None] = mapped_column(Integer)             # 1-12; null utk dokumen
    urut: Mapped[int] = mapped_column(Integer, nullable=False)     # nomor urut per (kode,tahun)
    perihal: Mapped[str | None] = mapped_column(Text)
    pihak: Mapped[str | None] = mapped_column(String(255))         # tujuan/pihak
    pembuat: Mapped[str | None] = mapped_column(String(120))
    file_ref: Mapped[str | None] = mapped_column(String(512))      # gdrive id / path
    # aktif / batal
    status: Mapped[str] = mapped_column(String(10), default="aktif")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KartuPemeliharaan(Base):
    """Satu entri kartu pemeliharaan/servis sebuah aset."""

    __tablename__ = "kantor_kartu_pemeliharaan"

    id: Mapped[int] = mapped_column(primary_key=True)
    aset_id: Mapped[int] = mapped_column(
        ForeignKey("kantor_aset.id", ondelete="CASCADE"), nullable=False
    )
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    # rutin / perbaikan / inspeksi / penggantian
    jenis: Mapped[str] = mapped_column(String(40), default="rutin")
    deskripsi: Mapped[str] = mapped_column(Text, nullable=False)
    biaya: Mapped[float | None] = mapped_column(Numeric(15, 2))
    pelaksana: Mapped[str | None] = mapped_column(String(120))
    # jadwal servis berikutnya → sumber reminder scheduler
    jadwal_berikutnya: Mapped[date | None] = mapped_column(Date)
    bukti_ref: Mapped[str | None] = mapped_column(String(512))  # gdrive id nota/foto
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
