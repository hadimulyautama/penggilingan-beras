"""Gudang 2 (Penyosohan) — PK masuk, intake ke silo/tumpukan, pindah tumpukan→silo.

Silo G2 = KOLAM CAMPURAN (boleh banyak sumber), beda dgn G1 (1 silo = 1 lot).
Stok silo/tumpukan DITURUNKAN dari intake + pindah − terpakai (lihat services).
Acuan: LOGIKA_SILO_GUDANG2.md.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin
from hmu_core import Armada


class PkPurchaseBatch(Base, TimestampMixin):
    """Pembelian PK dari luar (bukan transfer dari Gudang 1). Kode: PKB-YYYYMMDD-NN."""

    __tablename__ = "pk_purchase_batches"
    __table_args__ = (
        Index("uq_pk_purchase_batches_timbangan_hidup", "timbangan_transaksi_id", unique=True,
              postgresql_where=text("dibatalkan_pada IS NULL"),
              sqlite_where=text("dibatalkan_pada IS NULL")),
        Index("ix_pk_purchase_batches_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_batch: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    #: Dari siapa PK ini DIBELI — kosong bila ia tidak dibeli.
    #:
    #: Boleh NULL sejak migrasi 0065: PK jasa dititipkan pelanggan untuk
    #: disosoh, dan pemiliknya ada di `jasa_id`. `CHECK
    #: ck_pk_purchase_batches_beli_atau_jasa` menuntut TEPAT SATU terisi.
    #:
    #: ⚠ JANGAN mengakalinya dengan memasukkan pelanggan ke `suppliers` —
    #: jalur ini berbunyi "tak ada supplier_id → cari atau buat dari nama
    #: pihak", dan pemasok palsu akan ikut ke skor pemasok, laporan pembelian,
    #: dan HPP.
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    #: Pesanan jasa yang memiliki PK ini. NULL = milik pabrik.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))
    # Kosong = "menunggu bobot" (referensi bobot = tiket timbang; disinkron otomatis).
    berat_total_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    no_polisi_truk: Mapped[str | None] = mapped_column(String(20))
    armada_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_kendaraan.id"))
    armada: Mapped[Armada | None] = relationship()
    # Jenis PK luar: ks / kl / campuran / semi_ks (lebih luas dari G1 yg cuma KS/KL).
    jenis_pk: Mapped[str | None] = mapped_column(String(12))
    kadar_air_awal_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    tanggal_pembelian: Mapped[date] = mapped_column(Date, nullable=False)
    waktu_pembelian: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # baru / diterima / ditolak / di_silo / disosoh
    status_batch: Mapped[str] = mapped_column(String(20), default="baru")
    flag_unverified: Mapped[bool] = mapped_column(Boolean, default=True)
    # Tautan ke timbangan (shared DB) — FK di level DB saja (migrasi 0027). Lihat PurchaseBatch.
    timbangan_transaksi_id: Mapped[int | None] = mapped_column()
    sumber_berat: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")
    #: Perkiraan dari tara truk yang sama (QA P6, 21 September 2026): terisi
    #: saat batch lahir dari tiket yang belum ditimbang kedua, dan TETAP
    #: tersimpan sesudah netto sungguhan datang — selisihnya menguji anggapan
    #: "tara stabil" di rekonsiliasi. `sumber_berat='perkiraan'` selama masih
    #: berdiri di atas angka ini.
    berat_perkiraan_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: Peristiwa `pk_luar_masuk` yang melahirkan baris ini (Tahap 3) —
    #: terisi = cermin buku besar; kosong = jalur lama / manual.
    peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Cermin bertanda, bukan dihapus (lihat `app/models/cermin.py`).
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped["Supplier"] = relationship()  # noqa: F821
    verification: Mapped["PkPurchaseVerification | None"] = relationship(
        back_populates="batch", uselist=False
    )


class PkPurchaseVerification(Base, TimestampMixin):
    """Snapshot rata-rata QC PK luar dan peninggalan verifikasi harga."""

    __tablename__ = "pk_purchase_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    pk_purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("pk_purchase_batches.id"), unique=True, nullable=False
    )
    # QC (uji lab)
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    # % bekatul hasil uji lab (penyusutan saat disosoh)
    penyusutan_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    # butir kuning / gabah (belum terkupas) / merang (jerami, malai):
    # bersih / sedikit / sedang / banyak — skala yang sama untuk ketiganya.
    # gabah & merang ditambahkan 5 Oktober 2026 (keputusan pemilik).
    butir_kuning: Mapped[str | None] = mapped_column(String(10))
    gabah: Mapped[str | None] = mapped_column(String(10))
    merang: Mapped[str | None] = mapped_column(String(10))
    # deskripsi/catatan uji lab tambahan
    catatan_lab: Mapped[str | None] = mapped_column(String(255))
    # terima / tolak
    keputusan: Mapped[str | None] = mapped_column(String(10))
    alasan_tolak: Mapped[str | None] = mapped_column(String(255))
    # `potongan_kg`/`potongan_alasan` DIHAPUS 4 Oktober 2026 (keputusan
    # pemilik) — basis data produksi tak pernah memuat satu baris pun
    # berisi angka itu (0 dari 0 baris saat diperiksa), jadi tak ada
    # riwayat yang perlu dijaga. Bobot PK yang masuk Gudang 2 kini SELALU
    # sama dengan bobot tiket timbangnya; kalau bobot memang perlu
    # dikoreksi, tempatnya revisi tiket di Pos Timbang, bukan potongan
    # diam-diam di sini. Lihat migrasi yang menjatuhkan kolomnya.
    # Harga
    # ── PENINGGALAN: harga pindah ke keuangan 28 September 2026 ──
    #
    # Kolom-kolom di bawah ini TIDAK lagi ditulis maupun dibaca Pos Produksi.
    # Kolom QC di atas adalah snapshot rata-rata dari pk_purchase_qc_logs.
    # Setiap putaran disimpan sendiri; snapshot menjaga pembaca stok lama.
    # Dipertahankan untuk RIWAYAT: harga yang sudah tercatat adalah pembelian
    # sungguhan, dan hal pertama yang keuangan minta begitu mereka mengambil
    # alih adalah data lama. Kalau kolomnya sudah jatuh, tak ada yang bisa
    # mengembalikannya.
    #
    # Jangan dipakai lagi; jangan pula dihapus tanpa ekspor. Migrasi yang
    # menjatuhkannya boleh menyusul SESUDAH keuangan mengambil datanya, dan
    # atas permintaan pemilik.
    harga_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_biaya: Mapped[float | None] = mapped_column(Numeric(16, 2))
    # per_kg / total
    metode_harga: Mapped[str | None] = mapped_column(String(10))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")

    batch: Mapped["PkPurchaseBatch"] = relationship(back_populates="verification")


class PkPurchaseQcLog(Base):
    """Setiap pemeriksaan PK luar tersimpan sendiri, termasuk hasil lama."""
    __tablename__ = "pk_purchase_qc_logs"
    __table_args__ = (Index("ix_pk_qc_batch", "pk_purchase_batch_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pk_purchase_batch_id: Mapped[int] = mapped_column(ForeignKey("pk_purchase_batches.id"), nullable=False)
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    susut_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    butir_kuning: Mapped[str | None] = mapped_column(String(10))
    gabah: Mapped[str | None] = mapped_column(String(10))
    merang: Mapped[str | None] = mapped_column(String(10))
    catatan_lab: Mapped[str | None] = mapped_column(String(255))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Penulis QC lama tidak tersimpan; verified_by adalah penetap harga.
    input_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    asal_lama: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class PkGudang2Intake(Base, TimestampMixin):
    """Setiap PK yang MASUK ke Gudang 2 — dari beli luar atau transfer G1.

    tujuan: JENIS tempatnya (`silo` / `ditumpuk`); silo MANA di `silo_id`,
    NULL bila ditumpuk. Baris lama menyimpan `silo_a`/`silo_b` — lihat
    catatan pada `InternalTransfer.lokasi_tujuan`.
    Membawa snapshot HPP/kg (flag_hpp_belum_tersedia bila milling G1 belum verif).
    """

    __tablename__ = "pk_gudang2_intakes"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_pk_gudang2_intakes_silo", "silo_id"),
        Index("ix_pk_gudang2_intakes_waktu", "tanggal_masuk"),
        Index("uq_pk_gudang2_intakes_batch", "pk_purchase_batch_id",
              unique=True,
              postgresql_where=text("pk_purchase_batch_id IS NOT NULL AND dibatalkan_pada IS NULL"),
              sqlite_where=text("pk_purchase_batch_id IS NOT NULL AND dibatalkan_pada IS NULL")),
        Index("uq_pk_gudang2_intakes_transfer", "internal_transfer_id",
              unique=True,
              postgresql_where=text("internal_transfer_id IS NOT NULL AND dibatalkan_pada IS NULL"),
              sqlite_where=text("internal_transfer_id IS NOT NULL AND dibatalkan_pada IS NULL")),
        Index("ix_pk_gudang2_intakes_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # beli_luar / transfer_internal
    sumber_tipe: Mapped[str] = mapped_column(String(20), nullable=False)
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pk_purchase_batches.id")
    )
    internal_transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("internal_transfers.id")
    )
    # silo_a / silo_b / ditumpuk
    tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    #: NULL = belum punya angka saat masuk (PK luar yang truknya belum
    #: ditimbang kedua, tanpa tara — QA P6-02). Diisi poller dari batch-nya.
    berat_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: False bila `berat_kg` masih perkiraan / belum diketahui saat masuk.
    bobot_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                              server_default=text("true"))
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    flag_hpp_belum_tersedia: Mapped[bool] = mapped_column(Boolean, default=True)
    tanggal_masuk: Mapped[date] = mapped_column(Date, nullable=False)
    waktu_masuk: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Peristiwa `pk_masuk_g2` yang melahirkan baris ini (Tahap 3, aksi ketiga).
    peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Cermin bertanda, bukan dihapus (lihat `app/models/cermin.py`).
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Pesanan jasa yang memiliki PK ini. NULL = milik pabrik.
    #:
    #: Dari `internal_transfers.jasa_id` untuk PK kiriman Gudang 1; selalu NULL
    #: untuk PK beli luar — PK walk-in jasa belum dikerjakan, dan kolom yang
    #: bisa terisi lewat jalur yang belum ada adalah kolom yang akan terisi
    #: salah.
    #:
    #: ⚠ `pk_tumpukan_to_silo` TIDAK punya kolom ini, dan tak perlu: pemilik isi
    #: sebuah silo Gudang 2 dibaca dari intake-intake yang mengisinya — langsung
    #: maupun lewat pemindahan tumpukan. Lihat `jasa.pemilik_silo_g2`.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class PkTumpukanToSilo(Base, TimestampMixin):
    """Pemindahan PK dari tumpukan ke silo (khusus Operator Gudang 2, admin fallback).

    Bisa parsial (tidak harus semua tumpukan sekaligus). Kode: PTS-YYYYMMDD-NN.
    """

    __tablename__ = "pk_tumpukan_to_silo"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    pk_gudang2_intake_id: Mapped[int] = mapped_column(
        ForeignKey("pk_gudang2_intakes.id"), nullable=False
    )
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Peristiwa `pk_tumpukan_ke_silo` yang melahirkan baris ini (Tahap 3, aksi kelima).
    peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Cermin bertanda, bukan dihapus (lihat `app/models/cermin.py`).
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrokenKeSilo(Base, TimestampMixin):
    """Pemindahan broken (hasil samping sosoh) dari stok curah ke silo broken.

    Sebangun `PkTumpukanToSilo`: broken yang sudah tercatat `byproduct_stock`
    (lewat `catat_broken`) dipindah ke silo ber-`jenis_isi='broken'` supaya
    bisa disosoh ULANG sebagai bahan baku — keputusan pemilik 6 Oktober 2026.
    Kode: BKS-YYYYMMDD-NN.
    """

    __tablename__ = "broken_ke_silo"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    byproduct_stock_id: Mapped[int] = mapped_column(
        ForeignKey("byproduct_stock.id"), nullable=False
    )
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pemilik broken yang dipindah — DISALIN dari baris `byproduct_stock`
    #: sumbernya, bukan dibaca menyusul lewat join. Pola yang sama dengan
    #: `masukkan_pk_luar`: *"Pemiliknya DISALIN dari batch-nya, bukan dibaca
    #: menyusul… Tanpa baris ini, PK pelanggan berubah jadi PK pabrik tepat di
    #: pintu Gudang 2 — tanpa satu pun galat."* Di sini: broken pelanggan
    #: berubah jadi broken pabrik tepat saat ia dituang ke silo.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class BerasKeSilo(Base, TimestampMixin):
    """Beras (curah/berkemasan) dipindah jadi bahan baku silo — dua pintu,
    keputusan pemilik 8 Oktober 2026:

      · Silo Beras (`jenis_isi='beras'`) — beras GRADE (`jenis` salah satu
        `stok.BERAS_JENIS`) dicampur untuk disosoh ulang. Sebangun silo
        broken, "yang jelas beras... untuk campuran".
      · Silo A/B (`jenis_isi='pk'`, TAK berubah bentuknya) — `beras_putih`
        (mutu belum ditetapkan) ikut masuk sebagai bahan sosoh ulang.

    Asal dapat berupa proses penyosohan (curah atau kemasan hasil proses) atau
    baris stok barang jadi (mis. beras kemasan dari tiket timbang/retur).
    `polishing_process_id` nullable untuk sumber yang bukan proses; `source_type`,
    `source_id`, dan `product_sku_id` menjaga jejak stok yang dipindahkan.
    `jenis` WAJIB disimpan karena satu proses bisa menghasilkan beberapa grade.

    Kode: BRS-YYYYMMDD-NN.
    """

    __tablename__ = "beras_ke_silo"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    polishing_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("polishing_process.id"))
    #: Asal yang dikuras. Untuk beras curah hasil sosoh, isinya polishing/
    #: proses; barang kemasan dari tiket timbang atau retur menyimpan sumber
    #: stok aslinya di sini supaya riwayatnya tidak mengarang proses sosoh.
    source_type: Mapped[str] = mapped_column(String(20), nullable=False,
                                              default="polishing")
    source_id: Mapped[int | None] = mapped_column(Integer)
    product_sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_skus.id"))
    #: Grade yang dipindah — salah satu `stok.BERAS_JENIS`, atau "beras_putih".
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pemilik beras yang dipindah — DISALIN dari proses sumbernya (pola
    #: sama `BrokenKeSilo.jasa_id`), bukan dibaca menyusul lewat join.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class HasilSampingKeSilo(Base, TimestampMixin):
    """Pemindahan stok menir/reject hasil sosoh ke silo Gudang 2."""

    __tablename__ = "hasil_samping_ke_silo"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    polishing_process_id: Mapped[int] = mapped_column(
        ForeignKey("polishing_process.id"), nullable=False)
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class PolishingProcess(Base, TimestampMixin):
    """Proses penyosohan (PK silo → beras putih). Kode: POL-YYYYMMDD-NN.

    Bahan WAJIB dari silo (bukan tumpukan). 1-2 hari = 1 proses.
    """

    __tablename__ = "polishing_process"
    __table_args__ = (
        Index("ix_polishing_process_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_proses: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    waktu_mulai: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    waktu_selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pesanan jasa yang memiliki SELURUH bahan proses sosoh ini. NULL = pabrik.
    #:
    #: Diturunkan dari silo sumbernya saat sosoh dimulai (`pastikan_satu_jasa`
    #: atas pemilik tiap silo), lalu disimpan — dan dari sinilah hasilnya
    #: mewarisi pemilik lewat `jasa.pemilik_hasil()`.
    #:
    #: ⚠ JUGA jejak ASAL bekatul. Bekatul beralih milik ke pabrik
    #: (`byproduct_stock.jasa_id` NULL), tetapi pemilik barang berhak tahu
    #: berapa bekatul yang keluar dari prosesnya — dan jawabannya dibaca lewat
    #: `byproduct_stock.source_id` → proses ini → kolom ini. Tanpa kolom ini,
    #: pertanyaan itu tak punya jawaban sama sekali.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class PolishingSiloUsage(Base, TimestampMixin):
    """Pemakaian silo per proses penyosohan.

    berat_awal_kg: snapshot OTOMATIS saat proses mulai (stok silo saat itu).
    berat_masuk_kg: PK yang ditambahkan selama proses (silo boleh diisi lagi).
    berat_akhir_kg: input MANUAL operator saat selesai.
    berat_terpakai_kg: computed = awal + masuk − akhir (diisi saat selesai).
    """

    __tablename__ = "polishing_silo_usage"
    __table_args__ = (
        # Indeks dinamai apa adanya seperti di basis data — lihat catatan
        # pada `PurchaseBatch` di gudang1.py. Temuan QA X-19.
        Index("ix_polishing_silo_usage_proses", "polishing_process_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    polishing_process_id: Mapped[int] = mapped_column(
        ForeignKey("polishing_process.id"), nullable=False
    )
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    berat_awal_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    #: PK yang DITAMBAHKAN ke silo ini selama proses berjalan. Keputusan
    #: pemilik 12 September 2026: silo yang dipoles boleh diisi lagi, jadi
    #: terpakai = awal + masuk − akhir (bukan lagi awal − akhir). Dulu intake
    #: ke silo yang dipoles ditolak (P-K-11) supaya rumus lama tetap benar.
    berat_masuk_kg: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default=text("0"))
    berat_akhir_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    berat_terpakai_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))


class PolishingOutputLog(Base):
    """Satu ENTRI hasil penyosohan — yang keluar pada SATU prosesan.

    ⚠ ARTINYA BERUBAH 28 September 2026 (migrasi 0060). Sampai hari itu
    `berat_kg` KUMULATIF sejak awal proses dan pembacanya mengambil baris
    TERBARU per jenis. Kini tiap baris berdiri sendiri, dan pembacanya
    MENJUMLAH. Baris lama ikut diubah jadi selisihnya oleh migrasinya —
    mencampur dua arti pada satu kolom membuat seluruh Stok Produk salah tanpa
    satu pesan pun.

    Sebabnya permintaan operator: dalam satu penyosohan mereka berganti spek,
    dan tiap spek punya hasilnya sendiri. Dengan kumulatif, mencatat 200 kg
    yang baru menuntut mereka mengetik 500 — jumlah yang dihitung sendiri di
    kepala, sambil berdiri di mesin.

    jenis: grade beras (sayur/medium/medsuper/premium/beras_b) ATAU hasil
    samping (menir/broken/bekatul/reject).
    """

    __tablename__ = "polishing_output_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    polishing_process_id: Mapped[int] = mapped_column(
        ForeignKey("polishing_process.id"), nullable=False
    )
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Spek yang sedang dijalankan saat entri ini keluar — keputusan pemilik 28
    #: September 2026 ("ikut dicatat tiap entry"). Bebas teks: spek di pabrik
    #: lahir dari permintaan pembeli, bukan dari daftar yang bisa dibekukan.
    #: NULL pada baris yang lahir sebelum hari itu.
    spek: Mapped[str | None] = mapped_column(String(30))
    #: Yang keluar pada PROSESAN INI, bukan total sejak awal.
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    waktu_update: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PkRejection(Base, TimestampMixin):
    """PK luar yang DITOLAK saat QC & dikembalikan ke supplier. Kode: REJ-YYYYMMDD-NN.

    Register barang keluar (retur beli): PK tak pernah jadi stok. Plat truk
    disalin dari batch agar jelas kendaraan yang membawa kembali.
    """

    __tablename__ = "pk_rejections"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    pk_purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("pk_purchase_batches.id"), unique=True, nullable=False
    )
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    no_polisi_truk: Mapped[str | None] = mapped_column(String(20))
    alasan: Mapped[str | None] = mapped_column(String(255))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
