"""Buku besar peristiwa dan proyeksinya — tulang punggung baru pencatatan.

Tahap 3 rancang ulang (13 September 2026). Dasar usulannya: bagian yang paling
jarang salah di sistem ini adalah stok yang DIHITUNG dari baris pergerakan;
yang paling sering salah adalah yang menimpa angka dan menghapus baris (QA
P-K-01, P-K-08, P-K-09, P-K-10, P-K-21).

  · `peristiwa` — apa yang TERJADI, satu baris per kejadian, TAMBAH-SAJA.
    Ditegakkan trigger di Postgres (migrasi 0047), bukan disiplin: UPDATE
    dan DELETE ditolak basis data. Pembatalan adalah peristiwa lawan yang
    menunjuk aslinya lewat `membatalkan_id`.
  · `proyeksi_*` — keadaan yang diturunkan dari peristiwa, diperbarui di
    transaksi yang sama, dan bisa dibangun ulang dari nol
    (`services.peristiwa.bangun_ulang`). Tabel lama (mis. `purchase_batches`)
    tetap ditulis sebagai CERMIN supaya layar tak berubah — satu aksi per
    kali pindah ke sini, dan pembacanya menyusul.

Aksi di jalur ini: "Gabah masuk" (Gudang 1), "PK luar masuk" (Gudang 2) —
keduanya dari tiket timbang — "PK masuk Gudang 2" (ke silo / tumpukan,
dari PK luar maupun transfer Gudang 1), "Pemindahan PK G1 → G2" (transfer;
satu aksi = dua peristiwa dalam satu transaksi: dipindah, lalu masuk), dan
"Pindah tumpukan ke silo" (Gudang 2, operator).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
                        String, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: Jenis peristiwa yang dikenal. Namanya kata kerja lampau-nya kejadian di
#: pabrik, bukan nama tabel — tabel bisa berganti, kejadiannya tidak.
GABAH_MASUK = "gabah_masuk"
GABAH_MASUK_DIBATALKAN = "gabah_masuk_dibatalkan"
PK_LUAR_MASUK = "pk_luar_masuk"
PK_LUAR_MASUK_DIBATALKAN = "pk_luar_masuk_dibatalkan"
PK_MASUK_G2 = "pk_masuk_g2"
PK_MASUK_G2_DIBATALKAN = "pk_masuk_g2_dibatalkan"
PK_DIPINDAH_G1G2 = "pk_dipindah_g1g2"
PK_DIPINDAH_G1G2_DIBATALKAN = "pk_dipindah_g1g2_dibatalkan"
PK_TUMPUKAN_KE_SILO = "pk_tumpukan_ke_silo"
PK_TUMPUKAN_KE_SILO_DIBATALKAN = "pk_tumpukan_ke_silo_dibatalkan"
PK_TUMPUKAN_KE_SILO_KOREKSI_BOBOT = "pk_tumpukan_ke_silo_koreksi_bobot"
PK_MASUK_G2_KOREKSI_BOBOT = "pk_masuk_g2_koreksi_bobot"

TERCATAT, DIBATALKAN = "tercatat", "dibatalkan"


class Peristiwa(Base):
    __tablename__ = "peristiwa"
    __table_args__ = (
        Index("ix_peristiwa_jenis_waktu", "jenis", "waktu"),
        Index("ix_peristiwa_membatalkan", "membatalkan_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    jenis: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Waktu KEJADIAN menurut yang mencatat (WIB, berzona) — bukan jam server.
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                            server_default=func.now())
    pelaku_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    #: Kunci kiriman: kiriman yang sama dua kali (klik ganda, jaringan putus
    #: lalu ulang) hanya menghasilkan SATU peristiwa.
    kunci_kiriman: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    muatan: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    #: Peristiwa yang dibatalkan oleh peristiwa ini. Unik: satu kejadian
    #: hanya bisa dibatalkan sekali.
    membatalkan_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"), unique=True)


class ProyeksiGabahMasuk(Base):
    """Satu baris per peristiwa `gabah_masuk` — hidup maupun dibatalkan.

    Diturunkan seluruhnya dari `peristiwa.muatan`; tak ada kolom yang
    diketik orang. Constraint parsial menolak keadaan mustahil: satu tiket
    timbang dengan dua pencatatan yang sama-sama hidup.
    """

    __tablename__ = "proyeksi_gabah_masuk"
    __table_args__ = (
        Index("uq_proyeksi_gabah_masuk_tiket_hidup", "timbangan_transaksi_id", unique=True,
              postgresql_where=text("status = 'tercatat'"),
              sqlite_where=text("status = 'tercatat'")),
        Index("ix_proyeksi_gabah_masuk_tanggal", "tanggal"),
    )

    peristiwa_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"), primary_key=True)
    kode_batch: Mapped[str] = mapped_column(String(20), nullable=False)
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(Integer)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    nama_supplier: Mapped[str | None] = mapped_column(String(150))
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    sumber_berat: Mapped[str] = mapped_column(String(12), nullable=False)
    kondisi: Mapped[str] = mapped_column(String(10), nullable=False)
    no_polisi: Mapped[str | None] = mapped_column(String(20))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pelaku_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    #: tercatat | dibatalkan
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TERCATAT)
    dibatalkan_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Id baris cermin di `purchase_batches` saat dibuat — bukan FK, karena
    #: cerminnya dihapus saat dibatalkan (pembacanya masih menganggap "ada
    #: baris" = "ada gabah").
    purchase_batch_id: Mapped[int | None] = mapped_column(Integer)


class ProyeksiPkLuarMasuk(Base):
    """Satu baris per peristiwa `pk_luar_masuk` — kembaran proyeksi gabah
    untuk Gudang 2. Cerminnya `pk_purchase_batches`."""

    __tablename__ = "proyeksi_pk_luar_masuk"
    __table_args__ = (
        Index("uq_proyeksi_pk_luar_masuk_tiket_hidup", "timbangan_transaksi_id", unique=True,
              postgresql_where=text("status = 'tercatat'"),
              sqlite_where=text("status = 'tercatat'")),
        Index("ix_proyeksi_pk_luar_masuk_tanggal", "tanggal"),
    )

    peristiwa_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"), primary_key=True)
    kode_batch: Mapped[str] = mapped_column(String(20), nullable=False)
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(Integer)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    nama_supplier: Mapped[str | None] = mapped_column(String(150))
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    sumber_berat: Mapped[str] = mapped_column(String(12), nullable=False)
    #: ks / kl / campuran / semi_ks
    jenis_pk: Mapped[str | None] = mapped_column(String(12))
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    no_polisi: Mapped[str | None] = mapped_column(String(20))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pelaku_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TERCATAT)
    dibatalkan_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(Integer)


class ProyeksiPkMasukG2(Base):
    """Satu baris per peristiwa `pk_masuk_g2` — PK yang masuk ke silo atau
    tumpukan Gudang 2, dari PK luar maupun transfer Gudang 1. Cerminnya
    `pk_gudang2_intakes`. `hpp_per_kg` = potret saat masuk (harga yang
    diverifikasi belakangan mengisi cerminnya, belum menjadi peristiwa).
    Constraint parsial: satu batch PK luar / satu transfer hanya punya satu
    pemasukan yang hidup (P-K-10 sisi ganda, r01)."""

    __tablename__ = "proyeksi_pk_masuk_g2"
    __table_args__ = (
        Index("uq_proyeksi_pk_masuk_g2_batch_hidup", "pk_purchase_batch_id", unique=True,
              postgresql_where=text("status = 'tercatat' AND pk_purchase_batch_id IS NOT NULL"),
              sqlite_where=text("status = 'tercatat' AND pk_purchase_batch_id IS NOT NULL")),
        Index("uq_proyeksi_pk_masuk_g2_transfer_hidup", "internal_transfer_id", unique=True,
              postgresql_where=text("status = 'tercatat' AND internal_transfer_id IS NOT NULL"),
              sqlite_where=text("status = 'tercatat' AND internal_transfer_id IS NOT NULL")),
        Index("ix_proyeksi_pk_masuk_g2_silo", "silo_id"),
    )

    peristiwa_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"), primary_key=True)
    #: beli_luar / transfer_internal
    sumber_tipe: Mapped[str] = mapped_column(String(20), nullable=False)
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(Integer)
    internal_transfer_id: Mapped[int | None] = mapped_column(Integer)
    #: JENIS tempatnya: `silo` atau `ditumpuk` — silo MANA ada di `silo_id`.
    #: Baris lama menyimpan `silo_a`/`silo_b`; lihat catatan pada
    #: `InternalTransfer.lokasi_tujuan`.
    tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))   # NULL = belum diketahui (P6-02)
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: Kode penyosohan yang sedang memakai silo saat PK dituang (ikut jadi bahannya).
    ke_proses: Mapped[str | None] = mapped_column(String(20))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pelaku_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TERCATAT)
    dibatalkan_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    intake_id: Mapped[int | None] = mapped_column(Integer)


class ProyeksiTransferPk(Base):
    """Satu baris per peristiwa `pk_dipindah_g1g2` — PK hasil giling yang
    dikirim ke Gudang 2. Cerminnya `internal_transfers` (yang TIDAK dihapus
    saat dibatalkan: statusnya `dibatalkan`, pembacanya menyaring
    `terkirim`). `intake_peristiwa_id` menunjuk peristiwa `pk_masuk_g2`
    pasangannya."""

    __tablename__ = "proyeksi_transfer_pk"
    __table_args__ = (
        Index("ix_proyeksi_transfer_pk_proses", "milling_process_id"),
    )

    peristiwa_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"), primary_key=True)
    kode_transfer: Mapped[str] = mapped_column(String(20), nullable=False)
    milling_process_id: Mapped[int | None] = mapped_column(Integer)
    kode_proses: Mapped[str | None] = mapped_column(String(20))
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    jumlah_karung: Mapped[int | None] = mapped_column(Integer)
    berat_curah_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: JENIS tempatnya: `silo` atau `ditumpuk` — silo MANA ada di `silo_id`.
    #: Baris lama menyimpan `silo_a`/`silo_b`; lihat catatan pada
    #: `InternalTransfer.lokasi_tujuan`.
    lokasi_tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: KS / KL / MIX
    jenis: Mapped[str | None] = mapped_column(String(8))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pelaku_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TERCATAT)
    dibatalkan_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    intake_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    transfer_id: Mapped[int | None] = mapped_column(Integer)


class ProyeksiPindahTumpukanSilo(Base):
    """Satu baris per peristiwa `pk_tumpukan_ke_silo` — PK yang dipindah
    operator dari tumpukan Gudang 2 ke silo, boleh sebagian. Cerminnya
    `pk_tumpukan_to_silo`. `ke_proses` terisi bila dituang ke silo yang
    sedang dipoles (ikut jadi bahan proses itu)."""

    __tablename__ = "proyeksi_pindah_tumpukan_silo"
    __table_args__ = (
        Index("ix_proyeksi_pindah_tumpukan_silo_intake", "intake_id"),
        Index("ix_proyeksi_pindah_tumpukan_silo_silo", "silo_id"),
    )

    peristiwa_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"), primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Tumpukan sumber (`pk_gudang2_intakes.id`) dan peristiwa pemasukannya bila ada.
    intake_id: Mapped[int] = mapped_column(Integer, nullable=False)
    intake_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 3))
    jumlah_karung: Mapped[int | None] = mapped_column(Integer)
    jumlah_karung_50: Mapped[int | None] = mapped_column(Integer)
    berat_curah_kg: Mapped[float | None] = mapped_column(Numeric(12, 3))
    ke_proses: Mapped[str | None] = mapped_column(String(20))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pelaku_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TERCATAT)
    dibatalkan_peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    move_id: Mapped[int | None] = mapped_column(Integer)
