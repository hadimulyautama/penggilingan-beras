"""Gudang 1 — Proses Pecah Kulit (Milling) & buffer PK. Migrasi 0002."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    text,
    Index,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class MillingProcess(Base, TimestampMixin):
    """Proses pecah kulit per silo — gabah kering jadi PK. Kode lot giling:
    LOT-YYYYMMDD-NN (dulu MIL-; "lot" milik giling sejak pengeringan dilepas
    jadi PGR-, karena lot yang sesungguhnya terbentuk saat giling dimulai)."""

    __tablename__ = "milling_process"
    # ── Tak ada lagi indeks unik atas `silo_id` ──
    #
    # Dulu `uq_milling_process_silo_proses` menjaga "satu giling berjalan per
    # silo" lewat kolom ini. Aturannya TETAP BENAR; yang berubah, sejak satu
    # lot boleh datang dari beberapa silo (keputusan pemilik 24 September
    # 2026), kolom tunggal ini tak lagi menyebut seluruh silo yang dipakai —
    # jadi ia menjaga silo pertama saja dan membiarkan silo kedua terbuka.
    # Penjagaannya pindah ke baris silonya sendiri: `SiloStorage.
    # milling_process_id`, lihat catatan panjang di sana. Migrasi 0056.
    __table_args__ = (
        Index("ix_milling_process_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_proses: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    #: ⚠ PENINGGALAN — silo PERTAMA saja, dan TIDAK berwenang.
    #:
    #: Satu lot boleh datang dari beberapa silo sejak 24 September 2026, dan
    #: kolom ini cuma menyebut yang pertama. Ia dipertahankan supaya data lama
    #: dan laporan yang membacanya tidak mati sekaligus — TETAPI tak boleh lagi
    #: ada keputusan perilaku yang bergantung padanya. Yang benar selalu
    #: `milling_process_sources`; himpunan silonya diturunkan lewat
    #: `silo.silo_ids_proses`, dan "silo ini sedang digiling?" lewat
    #: `silo.giling_berjalan_untuk_silo`.
    #:
    #: Tiga tempat pernah memercayainya, dan ketiganya melahirkan kerusakan yang
    #: sama dengan tiga rupa: silo kedua ditawarkan lagi untuk digiling, tidak
    #: ikut dikosongkan, dan tidak ikut dikembalikan saat pembatalan. Kolom yang
    #: terlihat berwibawa padahal tinggal peninggalan adalah kolom yang akan
    #: dipakai lagi oleh orang berikutnya.
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    #: PENINGGALAN juga — salah satu baris silo saja ("baris lot bila ada").
    #: Lihat catatan pada `silo_id`.
    silo_storage_id: Mapped[int | None] = mapped_column(ForeignKey("silo_storage.id"))
    #: PENINGGALAN juga: sumber sesungguhnya di `milling_process_sources`, dan
    #: satu proses boleh memuat beberapa lot & batch sekaligus.
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    berat_gabah_masuk_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: False bila ada bahan yang masih perkiraan / belum diketahui saat giling
    #: dimulai (QA P6-03). Poller membetulkan `berat_gabah_masuk_kg` proses
    #: seperti ini WALAU sudah selesai, dan rekonsiliasi menyebutnya sampai
    #: final. Verifikasi output menunggu kolom ini true.
    bobot_masuk_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                                    server_default=text("true"))
    waktu_mulai: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    waktu_selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pesanan jasa yang memiliki SELURUH bahan lot ini. NULL = milik pabrik.
    #:
    #: Diturunkan dari sumbernya saat giling dimulai (`pastikan_satu_jasa` atas
    #: seluruh baris silo yang masuk), lalu disimpan — dan dari sinilah PK yang
    #: keluar mewarisi pemiliknya, sebab stok PK Gudang 1 adalah angka TURUNAN
    #: per lot giling, bukan baris stok tersendiri.
    #:
    #: Terisi berarti PK lot ini TIDAK muncul di daftar barang yang boleh
    #: dijual pabrik, dan rendemennya ditolak bila keluarannya melebihi
    #: masukannya: pada gabah pabrik itu salah pembukuan, pada barang
    #: pelanggan itu tagihan.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class MillingProgressLog(Base):
    """Monitoring berat kumulatif PK yang keluar (informatif)."""

    __tablename__ = "milling_progress_logs"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_milling_progress_proses", "milling_process_id",
              text("waktu_update DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    waktu_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    berat_kumulatif_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingQcLog(Base):
    """QC hasil PK oleh staff/admin (min. 1x per lot)."""

    __tablename__ = "milling_qc_logs"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_milling_qc_proses", "milling_process_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    susut_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    butir_kuning: Mapped[str | None] = mapped_column(String(10))
    gabah: Mapped[str | None] = mapped_column(String(10))
    merang: Mapped[str | None] = mapped_column(String(10))
    catatan_lab: Mapped[str | None] = mapped_column(String(255))
    # KS / KL / MIX
    kondisi: Mapped[str | None] = mapped_column(String(10))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingProcessVerification(Base, TimestampMixin):
    """Verifikasi berat output PK final oleh staff/admin."""

    __tablename__ = "milling_process_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), unique=True, nullable=False
    )
    berat_output_final_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")


class MillingProcessSource(Base):
    """Isi satu proses giling — satu baris per sumber yang ikut digiling.

    Memisahkan dua arti yang dulu dipaksa jadi satu tabel: `DryingLot` berarti
    satu PROSES PENGERINGAN (dryer, kadar air, pendinginan), sedangkan proses
    giling berarti APA YANG DIGILING BERSAMA. Selama satu silo hanya boleh
    berisi satu hal, keduanya kebetulan sama; begitu silo boleh dicampur,
    penunjuk tunggal di `MillingProcess` akan memilih salah satu dan
    mengabaikan sisanya — gabahnya tergiling, tetapi tidak tercatat.

    `berat_kg` disalin saat giling dimulai, bukan dihitung ulang belakangan:
    isi silo berubah setelah itu, dan berapa yang MASUK ke mesin tidak boleh
    ikut berubah bersamanya.
    """

    __tablename__ = "milling_process_sources"
    # Satu baris silo tidak boleh masuk dua kali ke proses yang sama —
    # kalau bisa, beratnya terhitung ganda dan HPP-nya ikut salah.
    __table_args__ = (
        UniqueConstraint("milling_process_id", "silo_storage_id",
                         name="uq_mps_proses_silo"),
        # Dinamai apa adanya seperti di basis data. `index=True` polos membuat
        # SQLAlchemy mengharapkan nama bawaannya, dan autogenerate lalu
        # mengusulkan membuat indeks baru sambil menghapus yang lama — indeks
        # yang sama, dua nama. Temuan QA X-19.
        Index("ix_mps_proses", "milling_process_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id", ondelete="CASCADE"), nullable=False
    )
    silo_storage_id: Mapped[int] = mapped_column(
        ForeignKey("silo_storage.id"), nullable=False
    )
    #: Tepat satu dari dua ini terisi — sama seperti di `SiloStorage`.
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_batches.id"))
    #: NULL = bahan ini belum punya angka saat giling dimulai (truk belum
    #: ditimbang kedua, tanpa tara). Bukan 0 — CHECK berat_positif menolak
    #: nol, dan memang nol itu bohong. Diisi poller begitu timbangnya ada.
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 3))
    #: Sisa yang tercatat saat SILO INI dibebaskan (`tutup_silo_giling`,
    #: migrasi 0070) — NULL berarti sumber ini MASIH TERIKAT, silonya masih
    #: dianggap sedang digiling. Sebangun `polishing_silo_usage.
    #: berat_akhir_kg` di Gudang 2, tetapi per BARIS, bukan per silo: satu
    #: silo di sini bisa punya banyak baris sumber (tiap pengisian melahirkan
    #: baris baru), dan membebaskannya menutup SELURUHNYA sekaligus — lihat
    #: `milling.tutup_silo_giling` untuk aturan pembagian sisanya antar baris.
    berat_akhir_kg: Mapped[float | None] = mapped_column(Numeric(12, 3))
    #: `berat_kg` dikurangi bagian yang jadi `berat_akhir_kg` baris ini —
    #: bagian yang benar-benar dianggap masuk mesin. NULL selama baris ini
    #: masih terikat, sama seperti `berat_akhir_kg`.
    berat_terpakai_kg: Mapped[float | None] = mapped_column(Numeric(12, 3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
