"""Master data produk & kemasan (modul inventory). Migrasi 0009.

Acuan: LOGIKA_PRODUK_JADI_INVENTORY.md + MASTER_RULES_AND_LOGIC.md §15-16, §21.
- Standar mutu beras putih = 4 (Sayur/Medium/MedSuper/Premium); admin-only ubah.
- Merk: 7 house + Polos (merk milik pembeli = label bebas, bukan master).
- SKU (kategori×merk×karung×ukuran) dibuat OTOMATIS saat pertama dipakai.
- Kemasan: harga/lembar dilacak (untuk HPP kemasan rata-rata tertimbang).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric,
                        String, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class RiceQualityStandard(Base, TimestampMixin):
    """Standar mutu beras putih (4). Beras B TIDAK punya standar. Admin-only ubah."""

    __tablename__ = "rice_quality_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class Brand(Base, TimestampMixin):
    """Merk. tipe: house (milik sendiri) / polos (tanpa merk). Merk pembeli =
    label bebas di transaksi, bukan baris di sini."""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # house / polos
    tipe: Mapped[str] = mapped_column(String(10), default="house")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PackagingMaterial(Base, TimestampMixin):
    """Jenis karung/kemasan: biasa, laminasi, putih, polos, bekas, karung_pk."""

    __tablename__ = "packaging_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(50), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class PackageSize(Base, TimestampMixin):
    """Ukuran kemasan (kg): 5, 10, 25, 48, 50."""

    __tablename__ = "package_sizes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ukuran_kg: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductSku(Base, TimestampMixin):
    """SKU produk = kategori × merk × jenis karung × ukuran. Dibuat on-demand.

    kategori: beras_putih / beras_b / broken / menir / reject / pk.
    brand_id NULL untuk hasil samping (broken/menir/reject) & PK.
    """

    __tablename__ = "product_skus"

    id: Mapped[int] = mapped_column(primary_key=True)
    kategori: Mapped[str] = mapped_column(String(20), nullable=False)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    packaging_material_id: Mapped[int] = mapped_column(
        ForeignKey("packaging_materials.id"), nullable=False
    )
    package_size_id: Mapped[int] = mapped_column(
        ForeignKey("package_sizes.id"), nullable=False
    )
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class PackagingPurchase(Base, TimestampMixin):
    """Pembelian kemasan (karung). Kode: PKP-YYYYMMDD-NN. Harga/lembar utk HPP."""

    __tablename__ = "packaging_purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    packaging_material_id: Mapped[int] = mapped_column(
        ForeignKey("packaging_materials.id"), nullable=False
    )
    package_size_id: Mapped[int] = mapped_column(
        ForeignKey("package_sizes.id"), nullable=False
    )
    # Merk karung (house/polos). NULL = data lama sebelum merk dilacak.
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    jumlah_lembar: Mapped[int] = mapped_column(Integer, nullable=False)
    harga_per_lembar: Mapped[float | None] = mapped_column(Numeric(12, 2))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # NULL = milik pabrik (bawaan — pembelian tak pernah menulis ini sendiri,
    # karung tak punya tiket timbang untuk menurunkan pemiliknya). Terisi
    # hanya lewat "Pindah kepemilikan karung" (packaging.
    # pindah_kepemilikan_karung), yang memecah baris pabrik yang sudah ada.
    #
    # ⚠ PELANGGAN, BUKAN JASA — sengaja berbeda dari sebelas tabel ber-
    # `jasa_id` lain (lihat migrasi 0075). Karung bukan barang yang
    # "dikembalikan" per pesanan; yang dilacak rekening per KONTAK.
    pelanggan_id: Mapped[int | None] = mapped_column(ForeignKey("pelanggan.id"))


class PackagingLoss(Base, TimestampMixin):
    """Kehilangan/kerusakan kemasan (mengurangi stok karung)."""

    __tablename__ = "packaging_losses"

    id: Mapped[int] = mapped_column(primary_key=True)
    packaging_material_id: Mapped[int] = mapped_column(
        ForeignKey("packaging_materials.id"), nullable=False
    )
    package_size_id: Mapped[int] = mapped_column(
        ForeignKey("package_sizes.id"), nullable=False
    )
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    jumlah_lembar: Mapped[int] = mapped_column(Integer, nullable=False)
    alasan: Mapped[str | None] = mapped_column(String(120))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Simetri rumus `hitung_stok_kemasan` saja — tak ada jalur tulis hari ini.
    # PELANGGAN, bukan jasa — sama alasan dengan `PackagingPurchase` di atas.
    pelanggan_id: Mapped[int | None] = mapped_column(ForeignKey("pelanggan.id"))


class FinishedGoodsStock(Base, TimestampMixin):
    """Stok barang jadi (dikemas): beras putih (grade), Beras B, broken/menir/
    reject kemasan. Masuk saat packing hasil produksi (atau retur kondisi baik).
    """

    __tablename__ = "finished_goods_stock"
    __table_args__ = (
        Index("ix_finished_goods_stock_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_sku_id: Mapped[int] = mapped_column(
        ForeignKey("product_skus.id"), nullable=False
    )
    # NULL untuk byproduct kemasan & Beras B (tak punya standar mutu).
    rice_quality_standard_id: Mapped[int | None] = mapped_column(
        ForeignKey("rice_quality_standards.id")
    )
    # polishing / reject_reprocessing / retur
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    jumlah_karung: Mapped[int] = mapped_column(Integer, nullable=False)
    berat_total_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pesanan jasa yang MEMILIKI beras ini. NULL = milik pabrik.
    #:
    #: ⚠ Setiap pembaca stok PABRIK menyaring `jasa_id IS NULL`. Tanpa itu Stok
    #: Produk menghitung beras pelanggan sebagai stok pabrik, lalu pabrik
    #: menjualnya — bukan angka yang salah, barang orang lain yang terjual, dan
    #: itu tak bisa diperbaiki dengan pembetulan pembukuan.
    #:
    #: Disimpan, bukan diturunkan dari `source_id` → `polishing_process.jasa_id`:
    #: saringan stok dibaca di hampir tiap layar, dan yang paling sering
    #: ditanyakan tak boleh dijawab paling mahal — lewat join ke tabel lain.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class ByproductStock(Base, TimestampMixin):
    """Stok hasil samping CURAH (hanya bekatul). Dijual per kg."""

    __tablename__ = "byproduct_stock"
    __table_args__ = (
        Index("ix_byproduct_stock_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    jenis_produk: Mapped[str] = mapped_column(String(20), nullable=False)
    # polishing / reject_reprocessing
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="tersedia")
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Pesanan jasa yang MEMILIKI hasil samping ini. NULL = milik pabrik.
    #:
    #: ⚠⚠ UNTUK BEKATUL, NULL ADALAH JAWABAN YANG BENAR — dan bukan karena
    #: bekatul jasa tak ada. Keputusan pemilik 12: *"bekatul tidak kembali bukan
    #: berarti barangnya tidak boleh keluar. bekatul otomatis berubah
    #: kepemilikan jadi milik kami. tetapi pemilik barang juga harus tau hasil
    #: bekatul dari tiap proses barang miliknya."*
    #:
    #: Jadi bekatul punya DUA fakta yang berpisah, dan kolom ini memikul yang
    #: pertama saja:
    #:
    #:     MILIK = pabrik         → kolom ini NULL, dan itu benar
    #:     ASAL  = JAS-2610-012   → lewat `source_id` → `polishing_process.jasa_id`
    #:
    #: Menyimpan ASAL di kolom ini akan membuat bekatul jadi stok pelanggan
    #: yang tak boleh dijual — kebalikan dari yang pemilik putuskan. Dan
    #: membiarkan NULL tanpa jejak asal akan menghapus hak pemilik barang untuk
    #: mengetahuinya. Keduanya ada; yang kedua tak butuh kolom.
    #:
    #: Menir, broken, dan reject KEMBALI ke pelanggan — untuk ketiganya kolom
    #: ini terisi. Yang menentukan `jasa.pemilik_hasil()`, satu tempat.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))


class ByproductPrice(Base, TimestampMixin):
    """Harga acuan byproduct (bekatul/broken/menir/reject) — untuk kredit HPP &
    penilaian stok. Baris terbaru per jenis = harga berlaku (histori terjaga)."""

    __tablename__ = "byproduct_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    harga_per_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


#: Keadaan satu transaksi barang keluar. Nilainya ditulis sekali di sini dan
#: dibaca layanan maupun layar — kata yang diketik ulang di tiga tempat akan
#: berbeda ejaannya di tempat keempat, dan saringan yang meleset diam-diam
#: menyembunyikan tugas dari layar operator.
OUT_PERINTAH, OUT_DIMUAT, OUT_SELESAI, OUT_BATAL = (
    "perintah", "dimuat", "selesai", "batal")
#: Yang masih berjalan — dipakai saringan antrean.
OUT_HIDUP = (OUT_PERINTAH, OUT_DIMUAT)


class OutgoingRecord(Base, TimestampMixin):
    """Barang keluar / dikirim. Kode: OUT-YYYYMMDD-NN. Proses jual lengkap
    (pelanggan/faktur/piutang) ada di modul Penjualan; di sini = dispatch fisik.

    ⭐ SATU TRANSAKSI, BANYAK BARANG — dan itu sudah begitu sejak awal lewat
    `OutgoingItem`. Yang baru sejak 28 September 2026 adalah KEADAANNYA:
    Admin memerintah, operator memuat, Admin memverifikasi (keputusan pemilik).
    Sampai hari itu barisnya lahir langsung "sudah terjadi", dan ketiga aksi
    pengirimannya masing-masing membuat baris BARU untuk SATU jenis barang —
    jadi satu truk berisi beras + broken + menir melahirkan tiga kode OUT-,
    tiga baris di kartu Stok Produk, dan tiga pencocokan untuk satu tiket
    timbang.

    `timbangan_transaksi_id` menunjuk tiket `arah='KELUAR'` dan NULL sampai
    langkah verifikasi — truk masuk kosong dan baru ditimbang bermuatan saat
    keluar, jadi tiketnya belum lengkap saat perintah dibuat maupun saat
    barangnya dimuat.
    """

    __tablename__ = "outgoing_records"
    __table_args__ = (
        # Satu tiket timbang keluar, satu transaksi yang HIDUP. Parsial, bukan
        # unik polos: yang dibatalkan harus boleh dicatat ulang, kalau tidak
        # truk yang salah dicatat tak punya jalan pulang. Syaratnya wajib sama
        # persis dengan migrasi 0061.
        Index("uq_outgoing_records_timbangan_hidup", "timbangan_transaksi_id",
              unique=True,
              postgresql_where=text("status <> 'batal'"),
              sqlite_where=text("status <> 'batal'")),
        Index("ix_outgoing_records_status", "status"),
        Index("ix_outgoing_records_jasa", "jasa_id",
              postgresql_where=text("jasa_id IS NOT NULL"),
              sqlite_where=text("jasa_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    #: ── DUA KOLOM BERDAMPINGAN untuk satu pembeli, dan yang kedua bukan
    #: kelebihan data ──
    #:
    #: `nama_pembeli` adalah CUPLIKAN nama pada hari truk itu berangkat;
    #: `pelanggan_id` TAUTANNYA ke master `pelanggan` — cermin lokal pelanggan
    #: Kledo (`type_id = 3`), yang disegarkan layanan Kantor sekali seminggu.
    #:
    #: Keduanya diisi bersama karena Kledo TIDAK punya "merge": kontak ganda
    #: dirapikan dengan memindahkan transaksinya lalu MENGHAPUS yang ganda.
    #: Kalau cuma tautannya yang disimpan, surat jalan tahun lalu kehilangan
    #: nama pembelinya pada hari seseorang merapikan daftar kontak.
    #:
    #: `pelanggan_id` BOLEH KOSONG, dan itu keputusan pemilik lewat bentuk
    #: borangnya: penyegarannya mingguan, jadi pembeli yang dibuat di Kledo
    #: pagi ini bisa belum ada di daftar. Mewajibkannya berarti truk berhenti
    #: di halaman menunggu keuangan membuat kontak.
    nama_pembeli: Mapped[str | None] = mapped_column(String(100))
    pelanggan_id: Mapped[int | None] = mapped_column(ForeignKey("pelanggan.id"))
    #: Pengambilan barang JASA oleh pemiliknya — NULL untuk penjualan biasa.
    #:
    #: Berbeda arti dari `pelanggan_id` di atasnya, dan keduanya memang bisa
    #: menunjuk orang yang sama: `pelanggan_id` menjawab "kepada siapa surat
    #: jalannya", `jasa_id` menjawab "ini mengurangi pesanan jasa yang mana".
    #: Satu kolom untuk dua pertanyaan akan membuat setiap penjualan ke
    #: pelanggan yang kebetulan juga menjasakan terbaca sebagai pengambilan.
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey("jasa.id"))
    # truk_sendiri / ekspedisi / sewa / pickup
    metode: Mapped[str | None] = mapped_column(String(20))
    no_polisi: Mapped[str | None] = mapped_column(String(20))
    nama_ekspedisi: Mapped[str | None] = mapped_column(String(100))
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    catatan: Mapped[str | None] = mapped_column(String(200))

    #: perintah → dimuat → selesai, dengan `batal` di sampingnya.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OUT_PERINTAH,
        server_default=OUT_SELESAI)
    #: Tiga pasang (oleh, waktu) TERPISAH — tiga orang, tiga tanggung jawab.
    #: Satu kolom "terakhir diubah oleh" menghapus justru pertanyaan yang kelak
    #: ditanyakan: siapa yang memerintahkan muatan yang ternyata salah.
    diperintah_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_perintah: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dimuat_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_muat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diverifikasi_oleh: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Tiket timbang KELUAR. NULL sampai verifikasi — lihat catatan kelas.
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(Integer)
    catatan_perintah: Mapped[str | None] = mapped_column(String(300))
    sebab_batal: Mapped[str | None] = mapped_column(String(300))
    #: Sebab selisih timbang yang BESAR — wajib diisi Admin saat menutup bila
    #: beda timbangan lawan catatan melewati ambang (lihat `barang_keluar.
    #: AMBANG_SELISIH_*`). Berisi = transaksi ini pernah ditandai, dan itu
    #: pertanyaan yang kelak ditanyakan. Kolom sendiri, bukan menumpang
    #: `catatan`: tanda yang bisa tertimpa tulisan lain bukan tanda.
    sebab_selisih: Mapped[str | None] = mapped_column(String(300))


class OutgoingItem(Base, TimestampMixin):
    """Item barang keluar. item_type: finished_goods (karung) / byproduct_curah
    (bekatul, kg) / pk_langsung (PK dari G1, kg→karung CEIL÷50). Harga OPSIONAL
    (penetapan harga penuh di modul Penjualan)."""

    __tablename__ = "outgoing_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    outgoing_record_id: Mapped[int] = mapped_column(
        ForeignKey("outgoing_records.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_sku_id: Mapped[int | None] = mapped_column(ForeignKey("product_skus.id"))
    rice_quality_standard_id: Mapped[int | None] = mapped_column(
        ForeignKey("rice_quality_standards.id")
    )
    jenis_byproduct: Mapped[str | None] = mapped_column(String(20))
    milling_process_id: Mapped[int | None] = mapped_column(ForeignKey("milling_process.id"))
    #: ── DUA ANGKA BERDAMPINGAN, dan yang kedua tak pernah menimpa yang
    #: pertama ── `*_perintah` milik Admin; `jumlah_karung`/`berat_kg` yang
    #: sudah ada berarti YANG BENAR-BENAR DIMUAT, dan dari sanalah stok
    #: berkurang. Muatan sungguhan memang berselisih dari perintahnya, dan
    #: selisih itu yang dilihat Admin saat verifikasi — selisih yang ditimpa
    #: berhenti jadi pertanyaan (pelajaran rantai permintaan PK).
    #:
    #: NULL pada baris lama: barang yang keluar sebelum 28 September 2026
    #: memang tak pernah punya perintah.
    berat_perintah_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    jumlah_karung_perintah: Mapped[int | None] = mapped_column(Integer)
    jumlah_karung: Mapped[int | None] = mapped_column(Integer)
    #: Yang BENAR-BENAR dimuat. 0 selama masih berstatus `perintah` — stok
    #: dihitung dari kolom ini, jadi perintah yang belum dimuat tak boleh
    #: mengurangi apa pun.
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    harga_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_harga: Mapped[float | None] = mapped_column(Numeric(16, 2))
