"""Gudang 1 — Produksi (Fase 1): pembelian gabah, pengeringan, silo."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class PurchaseBatch(Base, TimestampMixin):
    """Pembelian gabah per batch. 1 truk = 1 batch. Maks 3 batch/hari.

    Kode: GB-YYYYMMDD-NN
    """

    __tablename__ = "purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_batch: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    #: Dari siapa gabah ini DIBELI — kosong bila ia tidak dibeli.
    #:
    #: Boleh NULL sejak migrasi 0064: gabah jasa dititipkan pelanggan, dan
    #: pemiliknya ada di `jasa_id`. `CHECK ck_purchase_batches_beli_atau_jasa`
    #: menuntut TEPAT SATU dari keduanya terisi — pola yang sama sudah dipakai
    #: `MillingProcessSource` dan `SiloStorage`.
    #:
    #: ⚠ JANGAN mengakalinya dengan memasukkan pelanggan ke `suppliers`.
    #: Supplier palsu akan ikut ke `timbangan_skor_supplier`, laporan
    #: pembelian, dan HPP — tiga tempat yang akan menghitung barang yang tak
    #: pernah dibeli sebagai pembelian.
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    #: Pesanan jasa yang MEMILIKI gabah ini. NULL = milik pabrik.
    #:
    #: Satu kolom, satu arti: siapa yang berhak atas barangnya. Setiap pembaca
    #: stok PABRIK menyaring `jasa_id IS NULL` — tanpa itu, barang pelanggan
    #: ikut terhitung sebagai stok yang boleh dijual, dan kesalahan itu tak
    #: bisa diperbaiki dengan pembetulan pembukuan.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))
    # Kosong = "menunggu bobot" (referensi bobot ada di tiket timbang; disinkron otomatis).
    berat_total_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    no_polisi_truk: Mapped[str | None] = mapped_column(String(20))
    # basah / kering
    kondisi_gabah: Mapped[str] = mapped_column(String(10), nullable=False)
    kadar_air_awal_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    tanggal_pembelian: Mapped[datetime] = mapped_column(Date, nullable=False)
    waktu_pembelian: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # baru / dikeringkan / di_silo / digiling / selesai
    status_batch: Mapped[str] = mapped_column(String(20), default="baru")
    #: Mesin tempat gabah ini MENUNGGU, sebelum lotnya terbentuk.
    #:
    #: Berarti hanya pada satu keadaan singkat: sejak masuk mesin sampai
    #: "mulai pengeringan" membentuk lot. Setelah itu yang menyimpan mesinnya
    #: adalah `DryingLot.dryer_id` dan kolom ini dikosongkan lagi — supaya
    #: tidak ada dua tempat yang menyebut mesin untuk gabah yang sama, lalu
    #: suatu hari berbeda.
    dryer_id: Mapped[int | None] = mapped_column(ForeignKey("dryers.id"))
    flag_unverified: Mapped[bool] = mapped_column(Boolean, default=True)
    # ── Tautan ke timbangan (shared DB). 1 tiket timbang = maks 1 batch. ──
    # berat_total_kg/supplier/no_polisi diturunkan dari transaksi timbang; operator
    # tak input lagi. sumber_berat: 'nota' (berat_acuan_kg) | 'timbangan' (angka
    # timbangan) | 'manual' (tanpa jembatan). Basisnya satu tempat:
    # `timbang_link.SQL_BERAT_TIKET` — nota bila ada, lalu `berat_barang_kg`
    # (netto SUDAH dikurangi tara karung), netto sebagai cadangan tiket lama.
    # Tabel timbangan_transaksi dimiliki repo timbangan (shared DB) — TAK ada di metadata
    # app ini, jadi FK cukup di level DB (migrasi 0027). Di ORM: kolom Integer + unique.
    timbangan_transaksi_id: Mapped[int | None] = mapped_column()
    sumber_berat: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")
    #: Perkiraan dari tara truk yang sama (QA P6, 21 September 2026): terisi
    #: saat batch lahir dari tiket yang belum ditimbang kedua, dan TETAP
    #: tersimpan sesudah netto sungguhan datang — selisihnya menguji anggapan
    #: "tara stabil" di rekonsiliasi. `sumber_berat='perkiraan'` selama masih
    #: berdiri di atas angka ini.
    berat_perkiraan_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: Peristiwa `gabah_masuk` yang melahirkan baris ini (Tahap 3). Terisi =
    #: baris ini CERMIN dari buku besar; pembatalannya lewat peristiwa lawan.
    #: Kosong = dibuat jalur lama (manual / sebelum Tahap 3).
    peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Cermin BERTANDA, bukan dihapus: terisi = pencatatannya dibatalkan.
    #: Semua pembaca ORM menyaringnya lewat `app/models/cermin.py`.
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Kosong untuk gabah jasa — lihat `supplier_id`.
    supplier: Mapped["Supplier | None"] = relationship()  # noqa: F821
    verification: Mapped["PurchaseBatchVerification | None"] = relationship(
        back_populates="batch", uselist=False
    )

    __table_args__ = (
        # ── Indeks dideklarasikan APA ADANYA seperti di basis data ──
        #
        # Indeks yang dibuat migrasi tanpa disebut di model membuat
        # `alembic check` mengusulkan MENGHAPUSNYA tiap kali dijalankan —
        # termasuk indeks unik parsial yang justru menjaga keadaan mustahil
        # tak bisa terjadi. Usulan itu terbaca seperti migrasi biasa, dan yang
        # menerapkannya sambil terburu-buru mencabut penjaganya. Temuan QA X-19.
        Index("ix_purchase_batches_dryer", "dryer_id"),
        # Satu tiket satu pencatatan yang HIDUP — yang dibatalkan boleh dicatat lagi.
        Index("uq_purchase_batches_timbangan_hidup", "timbangan_transaksi_id", unique=True,
              postgresql_where=text("dibatalkan_pada IS NULL"),
              sqlite_where=text("dibatalkan_pada IS NULL")),
        # Parsial: baris berpemilik segelintir di antara riwayat bertahun-tahun
        # baris pabrik, dan indeks penuh atas kolom yang hampir selalu NULL
        # membayar biaya tulisnya tanpa mempercepat satu kueri pun.
        Index("ix_purchase_batches_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )


class PurchaseBatchVerification(Base, TimestampMixin):
    """Verifikasi harga gabah oleh staff/admin. Proses tidak ditahan."""

    __tablename__ = "purchase_batch_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_batches.id"), unique=True, nullable=False
    )
    # ── PENINGGALAN: harga pindah ke keuangan 28 September 2026 ──
    #
    # Kolom-kolom di bawah ini TIDAK lagi ditulis maupun dibaca Pos Produksi.
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
    # menunggu / terverifikasi
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")

    batch: Mapped[PurchaseBatch] = relationship(back_populates="verification")


class PurchaseBatchQc(Base, TimestampMixin):
    """QC gabah per truk: Lamur hanya dicatat untuk gabah basah."""

    __tablename__ = "purchase_batch_qc"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_batches.id"), unique=True, nullable=False
    )
    lamur: Mapped[bool | None] = mapped_column(Boolean)
    jumlah_sak_lamur: Mapped[int | None] = mapped_column(Integer)
    biji_hijau: Mapped[str] = mapped_column(String(20), nullable=False)
    densiti: Mapped[str] = mapped_column(String(10), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    __table_args__ = (
        CheckConstraint("jumlah_sak_lamur IS NULL OR jumlah_sak_lamur >= 0",
                        name="ck_purchase_batch_qc_sak_nonnegatif"),
        CheckConstraint("biji_hijau IN ('hampir_tidak_ada', 'sedikit', 'sedang', 'banyak')",
                        name="ck_purchase_batch_qc_biji_hijau"),
        CheckConstraint("densiti IN ('padat', 'sedang', 'empuk')",
                        name="ck_purchase_batch_qc_densiti"),
    )


class PurchaseBatchQcSample(Base, TimestampMixin):
    """Satu pencatatan QC truk; kadar air dibaca dua kali per pencatatan."""

    __tablename__ = "purchase_batch_qc_samples"
    __table_args__ = (UniqueConstraint(
        "purchase_batch_qc_id", "nomor_sampel", name="uq_purchase_batch_qc_sample_no"),
        CheckConstraint("nomor_sampel BETWEEN 1 AND 5", name="ck_purchase_batch_qc_sample_no"),
        CheckConstraint("kadar_air_1 BETWEEN 0 AND 100 AND kadar_air_2 BETWEEN 0 AND 100",
                        name="ck_purchase_batch_qc_sample_air_range"),
        CheckConstraint("jumlah_sak_lamur IS NULL OR jumlah_sak_lamur >= 0",
                        name="ck_purchase_batch_qc_sample_sak_nonnegatif"),
        CheckConstraint("biji_hijau IN ('hampir_tidak_ada', 'sedikit', 'sedang', 'banyak')",
                        name="ck_purchase_batch_qc_sample_biji_hijau"),
        CheckConstraint("densiti IN ('padat', 'sedang', 'empuk')",
                        name="ck_purchase_batch_qc_sample_densiti"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_batch_qc_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_batch_qc.id", ondelete="CASCADE"), nullable=False
    )
    nomor_sampel: Mapped[int] = mapped_column(Integer, nullable=False)
    kadar_air_1: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    kadar_air_2: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    lamur: Mapped[bool | None] = mapped_column(Boolean)
    jumlah_sak_lamur: Mapped[int | None] = mapped_column(Integer)
    biji_hijau: Mapped[str] = mapped_column(String(20), nullable=False)
    densiti: Mapped[str] = mapped_column(String(10), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class DryingLot(Base, TimestampMixin):
    """Lot pengeringan gabungan 2-3 batch. Tidak boleh campur basah & kering.

    Kode: PGR-YYYYMMDD-NN
    """

    __tablename__ = "drying_lots"
    __table_args__ = (
        Index("ix_drying_lots_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_lot: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    dryer_id: Mapped[int | None] = mapped_column(ForeignKey("dryers.id"))
    waktu_mulai_pengeringan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    waktu_selesai_pengeringan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Fase pendinginan (di dryer): mulai OTOMATIS saat pengeringan selesai,
    # selesai OTOMATIS saat gabah dipindah ke silo.
    #: Sampai berapa gabah ini dikeringkan — ditetapkan SEBELUM mesin
    #: dinyalakan. Bisa berbeda antar muatan, jadi ia milik lot, bukan setelan
    #: aplikasi. Yang di setelan hanya nilai bawaannya.
    target_kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    #: Mode mesin yang dipakai: "15T".."35T". KONFIRMASI bahwa operator sudah
    #: menyetelnya di mesin — aplikasi ini tidak tersambung ke dryer dan tidak
    #: bisa menyetelnya sendiri.
    mode_dryer: Mapped[str | None] = mapped_column(String(8))
    waktu_mulai_pendinginan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    waktu_selesai_pendinginan: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pesanan jasa yang memiliki SELURUH isi lot ini. NULL = milik pabrik.
    #:
    #: Satu lot tak boleh bercampur pemilik — `pastikan_satu_jasa()` menolaknya
    #: di `masuk_dryer`, `add_batches_to_lot`, dan `start_drying`. Ditolak,
    #: bukan diperingatkan: akibatnya barang orang lain, bukan angka.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))

    lot_batches: Mapped[list["DryingLotBatch"]] = relationship(
        back_populates="drying_lot"
    )
    moisture_logs: Mapped[list["DryingMoistureLog"]] = relationship(
        back_populates="drying_lot"
    )


class DryingLotBatch(Base):
    """Junction lot <-> batch. Validasi kondisi gabah harus sama (di service)."""

    __tablename__ = "drying_lot_batches"
    __table_args__ = (
        UniqueConstraint("drying_lot_id", "purchase_batch_id", name="uq_lot_batch"),
        Index("uq_drying_lot_batches_batch", "purchase_batch_id", unique=True,
              postgresql_where=text("purchase_batch_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int] = mapped_column(
        ForeignKey("drying_lots.id"), nullable=False
    )
    purchase_batch_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_batches.id"), nullable=False
    )

    drying_lot: Mapped[DryingLot] = relationship(back_populates="lot_batches")
    batch: Mapped[PurchaseBatch] = relationship()


class DryingMoistureLog(Base):
    """Log kadar air, wajib minimal tiap 5 jam. Notifikasi jika terlambat."""

    __tablename__ = "drying_moisture_logs"
    __table_args__ = (
        Index("ix_drying_moisture_lot", "drying_lot_id",
              text("waktu_update DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int] = mapped_column(
        ForeignKey("drying_lots.id"), nullable=False
    )
    waktu_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: Angka yang terbaca pada mesin dryer sendiri.
    kadar_air_indikator: Mapped[float | None] = mapped_column(Numeric(5, 2))
    #: RATA-RATA empat sampel alat tes di bawah. Dipertahankan sebagai kolom
    #: tersendiri supaya setiap pembaca lama terus bekerja tanpa disentuh.
    kadar_air_tes_manual: Mapped[float | None] = mapped_column(Numeric(5, 2))
    #: Empat titik sampel dengan alat tes kadar air, MENTAH.
    #:
    #: Disimpan mentah karena rata-rata tak bisa dibongkar kembali, dan
    #: sebaran keempat angka inilah yang memberi tahu apakah gabahnya kering
    #: merata atau baru bagian atasnya. Satu titik saja bisa kebetulan
    #: mengenai bagian paling basah — itu sebabnya diambil empat.
    kadar_air_tes_1: Mapped[float | None] = mapped_column(Numeric(5, 2))
    kadar_air_tes_2: Mapped[float | None] = mapped_column(Numeric(5, 2))
    kadar_air_tes_3: Mapped[float | None] = mapped_column(Numeric(5, 2))
    kadar_air_tes_4: Mapped[float | None] = mapped_column(Numeric(5, 2))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    drying_lot: Mapped[DryingLot] = relationship(back_populates="moisture_logs")


class DryingCoolingLog(Base):
    """Log pendinginan gabah — tetap di dryer, hanya sirkulasi udara.

    Bukan proses berpindah / berprogres; sekadar catatan timestamp + catatan.
    """

    __tablename__ = "drying_cooling_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int] = mapped_column(
        ForeignKey("drying_lots.id"), nullable=False
    )
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    catatan: Mapped[str | None] = mapped_column(String(255))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class SiloMovingLog(Base):
    """Log proses pemindahan gabah dari dryer ke silo (butuh waktu).

    Sekadar catatan kondisional (mulai/selesai). State sesungguhnya (gabah di
    silo, dryer kosong) ditangani oleh silo_storage.
    """

    __tablename__ = "silo_moving_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    silo_id: Mapped[int | None] = mapped_column(ForeignKey("silos.id"))
    # mulai / selesai
    tipe: Mapped[str] = mapped_column(String(10), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    catatan: Mapped[str | None] = mapped_column(String(255))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class SiloStorage(Base, TimestampMixin):
    """Penyimpanan gabah kering di silo. 1 silo = 1 lot sekaligus.

    Silo dianggap kosong saat milling selesai (bukan saat gabah keluar fisik).
    """

    __tablename__ = "silo_storage"
    __table_args__ = (
        Index("ix_silo_storage_lot", "drying_lot_id"),
        Index("ix_silo_storage_silo_status", "silo_id", "status"),
        # Dua indeks unik PARSIAL: satu batch hanya boleh berada di satu silo
        # SELAMA ia masih terisi. Tanpa syarat statusnya, riwayat lama ikut
        # terlarang dan gabah yang pernah masuk tak bisa masuk lagi.
        Index("uq_silo_storage_batch_terisi", "purchase_batch_id", unique=True,
              postgresql_where=text(
                  "purchase_batch_id IS NOT NULL AND status = 'terisi'")),
        Index("uq_silo_storage_lot_terisi", "drying_lot_id", unique=True,
              postgresql_where=text(
                  "drying_lot_id IS NOT NULL AND status = 'terisi'")),
        # Baris yang sedang berada di dalam mesin giling — lihat catatan pada
        # `milling_process_id` di bawah. Parsial: yang menarik cuma yang terisi
        # klaimnya, dan itu segelintir baris di antara riwayat bertahun-tahun.
        Index("ix_silo_storage_giling", "milling_process_id",
              postgresql_where=text("milling_process_id IS NOT NULL")),
        Index("ix_silo_storage_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    # dari_pengeringan / langsung_kering
    tipe_masuk: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Pesanan jasa yang memiliki baris isi silo ini. NULL = milik pabrik.
    #:
    #: Diturunkan dari lot/batch sumbernya saat barisnya dibuat, lalu DISIMPAN:
    #: "silo ini isinya milik siapa" ditanyakan pada setiap penuangan dan setiap
    #: giling, dan menjawabnya lewat dua join ke batch berarti pertanyaan yang
    #: paling sering ditanyakan dijawab paling mahal — serta pagar balapannya
    #: harus mengunci baris di tabel lain.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))
    tanggal_masuk: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tanggal_keluar: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # terisi / kosong
    status: Mapped[str] = mapped_column(String(20), default="terisi")
    #: KLAIM: proses giling yang sedang memakai baris ini, atau NULL.
    #:
    #: Bukan "himpunan silo sebuah proses" — itu diturunkan dari
    #: `milling_process_sources` dan tak perlu disimpan dua kali. Kolom ini
    #: menjawab satu pertanyaan lain yang TIDAK BISA dijawab dengan aman
    #: sesudahnya: "apakah baris ini sudah masuk mesin?" pada detik dua
    #: operator menekan "Mulai giling" bersamaan.
    #:
    #: Kenapa bukan indeks unik parsial seperti pagar-pagar lain di app ini:
    #: syaratnya ("prosesnya berstatus 'proses'") tinggal di BARIS TABEL LAIN,
    #: dan indeks hanya bisa menguji baris miliknya sendiri. Pemicu pun tak
    #: menolong — di READ COMMITTED ia tak melihat baris tetangga yang belum
    #: di-commit, jadi dua penekan tetap sama-sama lolos.
    #:
    #: Yang dipakai: SATU kolom pada baris yang diperebutkan, direbut dengan
    #: `UPDATE … WHERE milling_process_id IS NULL`. Postgres mengunci barisnya
    #: lalu MENGUJI ULANG syaratnya sesudah kunci didapat, jadi yang kedua
    #: menerima "0 baris" — bukan dua klaim yang sama-sama berhasil.
    #:
    #: Dilepas saat giling selesai (bersama `status = 'kosong'`) dan saat
    #: pembatalan; proses yang dihapus melepaskannya lewat ON DELETE SET NULL.
    milling_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("milling_process.id", ondelete="SET NULL", use_alter=True)
    )
    #: Berapa kg baris ini SUDAH dikeluarkan untuk dikemas+ditimbang (pesan
    #: kerja 7 Oktober 2026, butir 6 — migrasi 0077). Jalan keluar BARU dari
    #: silo, selain giling — gudang1.gabah_kering.keluarkan_untuk_kemasan()
    #: menaikkan kolom ini lewat SQL (`+=`), bukan baca-lalu-tulis, pola yang
    #: sama dengan `MillingProcess.berat_gabah_masuk_kg` (P-K-14): dua
    #: pengeluaran bersamaan yang membaca nilai lama di Python akan saling
    #: menghapus tambahan satu sama lain.
    #:
    #: ⚠ `_row_bobot` WAJIB menguranginya dari bobot baris — tanpa itu silo
    #: yang gabahnya sudah habis dikemas tetap terbaca penuh, dan isian
    #: berikutnya ditolak atas dasar stok yang sudah tak ada (pola yang sama
    #: dengan pesan 8 & 11: "jalan keluar baru wajib lahir bersama suku
    #: hitungannya").
    dikemas_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False,
                                               server_default="0")


class GabahKeringLot(Base, TimestampMixin):
    """Satu KELUARAN gabah kering dari silo — dikeluarkan, DITIMBANG (satu
    angka global, bukan per karung — "gabah yang datang kan langsung
    ditimbang global", keputusan pemilik 7 Oktober 2026), lalu ditumpuk.

    BUKAN barang jadi — gabah tetap BAHAN (`/stok`, bukan `/stok-produk`).
    Dan BUKAN `finished_goods_stock`: usul pertama memakai tabel itu lalu
    DICABUT sendiri — gabah tak punya ukuran karung, dan tabel itu memaksa
    anggapannya (`ProductSku.package_size_id` wajib isi).

    Jalan keluarnya meniru `pk_langsung` (PK dijual langsung dari Gudang 1),
    bukan `finished_goods`: SATU angka bobot, TANPA SKU, tanpa ukuran karung,
    tanpa jumlah karung wajib. Saldo = `berat_timbang_kg` − dibongkar kembali
    ke silo (`GabahKeringBongkar`) − keluar (`OutgoingItem.item_type=
    "gabah_langsung"`) — sebangun `transfer.saldo_pk`.

    ⚠⚠ `berat_timbang_kg` BUKAN riwayat — ia pengukuran TERAKHIR, DIGANTI di
    tempat tiap kali ditimbang ulang (pesan kerja 12B: gabah boleh dikeringkan
    lagi, lalu ditimbang lagi). Jejak penimbangan sebelumnya ada di
    `activity_logs`, bukan di sini — riwayat yang bisa dijumlahkan orang akan
    dijumlahkan orang, dan susut yang benar HANYA `basah pertama − timbang
    TERAKHIR`, tak pernah penjumlahan per-pengeringan.
    """

    __tablename__ = "gabah_kering_lots"
    __table_args__ = (
        Index("ix_gabah_kering_lots_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_lot: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    #: Baris silo asalnya — untuk menyambung ke bobot basah pembanding pagar
    #: fisika (lihat `gabah_kering._berat_basah_pembanding`) dan untuk jejak.
    silo_storage_id: Mapped[int] = mapped_column(
        ForeignKey("silo_storage.id"), nullable=False
    )
    #: Pesanan jasa yang memiliki lot ini. NULL = milik pabrik. Disalin dari
    #: `silo_storage.jasa_id` SEKALI saat lot dibuat, lalu disimpan — pola
    #: yang sama dengan `SiloStorage.jasa_id` sendiri.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))
    #: Bobot TERUKUR terakhir — lihat docstring kelas. DIISI DARI TIMBANGAN,
    #: bukan dihitung (`jumlah_karung × ukuran`) — gabah tak punya ukuran
    #: karung baku, dan bobot ini BOLEH tidak bulat (100 karung bisa 4.930 kg).
    berat_timbang_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    #: Keterangan SAJA, untuk menyusun di gudang — BUKAN dasar bobot, dan
    #: BUKAN wajib diisi.
    jumlah_karung: Mapped[int | None] = mapped_column(Integer)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu_timbang: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class GabahKeringBongkar(Base, TimestampMixin):
    """Satu kali tumpukan gabah kering DIBONGKAR kembali ke silo — WHOLE-LOT
    (seluruh sisa lot, bukan sebagian — lihat `gabah_kering.bongkar_ke_silo`
    untuk alasannya). `silo_storage_id` menunjuk baris BARU yang dibuat
    `masuk_silo` untuk muatan ini, dikreditkan `berat_timbang_kg` LOT ini
    (pengukuran TERAKHIR) — BUKAN bobot batch asalnya (pesan kerja 12A butir
    4b: memakai bobot batch akan menggelembungkan isi silo dan menjatuhkan
    rendemen giling berikutnya, kesalahan bentuk yang sama dengan nota-vs-
    timbangan 25 September)."""

    __tablename__ = "gabah_kering_bongkar"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_pindah: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    gabah_kering_lot_id: Mapped[int] = mapped_column(
        ForeignKey("gabah_kering_lots.id"), nullable=False
    )
    silo_storage_id: Mapped[int] = mapped_column(
        ForeignKey("silo_storage.id"), nullable=False
    )
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class JedaProses(Base):
    """Satu kali proses berhenti sementara, berikut sebabnya.

    Tabel tersendiri, bukan kolom pada lot: satu proses bisa berhenti
    berkali-kali dalam sehari, dan yang berguna justru JUMLAH PER SEBAB —
    "mesin pendukung memakan dua jam sehari" adalah belanja, bukan keluhan.
    Kolom pada lot hanya bisa menyimpan yang terakhir, dan yang terakhir
    hampir tak pernah yang terbesar.

    `selesai` kosong berarti prosesnya SEDANG berhenti sekarang.
    """

    __tablename__ = "jeda_proses"
    __table_args__ = (
        Index("ix_jeda_proses_drying_lot_id", "drying_lot_id"),
        Index("ix_jeda_proses_milling_process_id", "milling_process_id"),
        Index("ix_jeda_proses_polishing_process_id", "polishing_process_id"),
        Index("ix_jeda_proses_mulai", "mulai"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 'pengeringan' | 'giling' | 'penyosohan'. Tersirat dari kolom mana yang
    #: terisi, tetapi disimpan supaya laporan mengelompokkan tanpa menebak.
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    milling_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("milling_process.id")
    )
    #: Penyosohan Gudang 2 — sejak 12 September 2026 ia pun bisa berhenti
    #: sementara (keputusan pemilik, aplikasi operator Gudang 2).
    polishing_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("polishing_process.id")
    )
    sebab: Mapped[str] = mapped_column(String(120), nullable=False)
    mulai: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dicatat_oleh: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
