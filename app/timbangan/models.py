"""Model DB modul Timbangan (prefiks tabel `timbangan_`).

LINGKUP: murni timbangan. **Tidak ada kolom harga atau nilai uang di mana pun** —
operator pos timbang tidak boleh mengetahui harga. Larangan itu ditegakkan oleh
ketiadaan kolom, bukan oleh penyembunyian di tampilan.

Prinsip pemodelan (RANCANGAN §9.1):

  a. Aturan hidup di data      → menambah komoditas = satu baris `timbangan_jenis`
  b. Salinan aturan di transaksi → revisi SOP tidak mengubah riwayat
  c. Muatan selalu berupa baris  → masuk satu baris, keluar beberapa
  d. Tidak ada kolom harga/potongan
  e. Tara standar tidak ditimpa  → sampling baru = baris baru
  f. Angka timbangan mentah      → pembulatan tera sudah dikerjakan alat
  g. Nomor transaksi dibentuk di perangkat → syarat kerja tanpa jaringan

TIDAK membuat master tandingan: identitas mitra tetap di `suppliers`
(disinkronkan dari Kledo lewat `suppliers.kledo_contact_id`), identitas orang
tetap di `users`.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

# Numeric tanpa Decimal → aritmetika float konsisten di seluruh lapisan.
KG = Numeric(14, 3, asdecimal=False)
KG_KECIL = Numeric(9, 4, asdecimal=False)
PCT = Numeric(9, 4, asdecimal=False)

# ── Peran login ───────────────────────────────────────────────────────────
ROLE_PETUGAS = "PETUGAS"
ROLE_PENGAWAS = "PENGAWAS"
ROLE_ADMIN = "ADMIN"
ROLES = (ROLE_PETUGAS, ROLE_PENGAWAS, ROLE_ADMIN)
ROLE_LABEL = {
    ROLE_PETUGAS: "Petugas Timbang",
    ROLE_PENGAWAS: "Pengawas",
    ROLE_ADMIN: "Admin",
}

# ── Siklus hidup transaksi ────────────────────────────────────────────────
TIKET_TERBUKA = "TERBUKA"          # timbang pertama sudah, kedua belum
TIKET_SELESAI = "SELESAI"
TIKET_DITUTUP_PAKSA = "DITUTUP_PAKSA"

TRX_AKTIF = "AKTIF"
TRX_VOID = "VOID"                  # tidak pernah dihapus permanen

CARA_DUA_KALI = "DUA_KALI"
CARA_SEKALI = "SEKALI"             # jasa timbang, tanpa timbang kosong

# ── Pemeriksaan (SOP butir 6) ─────────────────────────────────────────────
PEMERIKSAAN_DIBUKA = "DIBUKA"
PEMERIKSAAN_SELESAI = "SELESAI"

STATUS_SUPPLIER = ("AKTIF", "PANTAU", "INVESTIGASI", "NONAKTIF")

JENIS_FOTO = {
    "ACUAN": "Foto nota / surat jalan",
    "TIMBANG_1": "Foto display timbang pertama",
    "TIMBANG_2": "Foto display timbang kedua",
    "MUATAN": "Foto muatan",
    "LAIN": "Foto lain",
}


# ══════════════════════════════════════════════════════════════════════════
# Master aturan
# ══════════════════════════════════════════════════════════════════════════

class TimbanganJenis(Base, TimestampMixin):
    """Aturan per komoditas — cerminan `logic.AturanJenis` di database.

    Menambah komoditas berarti menambah SATU baris di sini; tidak ada kode yang
    perlu diubah. Nilai baris ini disalin ke tiap transaksi saat disimpan, jadi
    merevisi aturan tidak pernah menggeser status transaksi lama.
    """

    __tablename__ = "timbangan_jenis"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(80), nullable=False)
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # MASUK / KELUAR / BEBAS
    arah: Mapped[str] = mapped_column(String(10), nullable=False)
    # ACUAN_NOTA / ACUAN_SURAT_JALAN / ACUAN_TIDAK_ADA
    acuan: Mapped[str] = mapped_column(String(24), nullable=False)
    # TARA_TETAP / TARA_SAMPLING / TARA_MANUAL
    sumber_tara: Mapped[str] = mapped_column(String(20), nullable=False)
    tara_tetap_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)
    tara_bawaan_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)

    # AMBANG_PER_TON / AMBANG_PER_KARUNG / AMBANG_TETAP / AMBANG_TIDAK_ADA
    ambang_jenis: Mapped[str] = mapped_column(String(24), nullable=False)
    ambang_nilai: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)
    # ARAH_SIMETRIS / ARAH_KURANG_SAJA / ARAH_TIDAK_BOLEH_KURANG
    ambang_arah: Mapped[str] = mapped_column(String(28), nullable=False)
    ambang_investigasi_nilai: Mapped[float | None] = mapped_column(KG_KECIL)

    # Hasil kontrol rahasia (gabah) atau boleh dilihat pengirim (PK).
    rahasia: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cetak_bukti: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    masa_berlaku_tara_hari: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktif")
    catatan: Mapped[str | None] = mapped_column(Text)


class TimbanganConfig(Base, TimestampMixin):
    """Setelan operasional yang boleh diubah Admin tanpa deploy ulang.

    Hanya memuat kunci yang terdaftar di `app.timbangan.setelan.DAFTAR`; kunci
    lain diabaikan. Baris yang tidak ada berarti "pakai nilai dari environment",
    jadi menghapus satu baris mengembalikan setelan ke bawaannya.

    Yang SENGAJA tidak boleh masuk sini: ambang kontrol, tara, dan aturan
    komoditas. Semua itu milik `timbangan_jenis`, karena merevisinya berarti
    merevisi cara perusahaan menilai kejujuran timbangan.
    """

    __tablename__ = "timbangan_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    kunci: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nilai: Mapped[str] = mapped_column(String(120), nullable=False)
    diubah_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))


# ══════════════════════════════════════════════════════════════════════════
# Master pendukung
# ══════════════════════════════════════════════════════════════════════════

class TimbanganAkun(Base, TimestampMixin):
    """Akun login webapp. Ditautkan ke `users` bila orangnya sudah terdaftar."""

    __tablename__ = "timbangan_akun"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_PETUGAS)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktif")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    # Kode perangkat yang dipegang orang ini — dipakai membentuk nomor
    # transaksi di perangkat (TRX-20260823-P1-007) agar tidak bentrok.
    perangkat_kode: Mapped[str | None] = mapped_column(String(8))
    terakhir_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def role_label(self) -> str:
        return ROLE_LABEL.get(self.role, self.role)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_pengawas(self) -> bool:
        """Pengawas & admin — boleh melihat SEMUA transaksi dan memeriksa."""
        return self.role in (ROLE_PENGAWAS, ROLE_ADMIN)


class TimbanganKendaraan(Base, TimestampMixin):
    """Master armada. Nomor polisi dinormalkan (huruf besar, tanpa spasi ganda)."""

    __tablename__ = "timbangan_kendaraan"

    id: Mapped[int] = mapped_column(primary_key=True)
    nomor_polisi: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    catatan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktif")


class TimbanganSupplierProfil(Base, TimestampMixin):
    """Atribut monitoring supplier (1:1 dengan `suppliers`).

    Sengaja terpisah dari `suppliers` agar sinkronisasi Kledo nanti bebas
    menimpa data identitas tanpa menyentuh catatan & status monitoring kita.
    """

    __tablename__ = "timbangan_supplier_profil"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), unique=True, nullable=False
    )
    wilayah: Mapped[str | None] = mapped_column(String(100))
    # AKTIF / PANTAU / INVESTIGASI / NONAKTIF
    status_monitoring: Mapped[str] = mapped_column(
        String(20), nullable=False, default="AKTIF"
    )
    catatan: Mapped[str | None] = mapped_column(Text)


class TimbanganTaraStandar(Base, TimestampMixin):
    """Hasil sampling tara karung per pihak × komoditas.

    Tidak pernah ditimpa: sampling ulang menulis baris baru dan menandai yang
    lama DIGANTI. Dengan begitu transaksi lama selalu bisa dijelaskan dengan
    angka tara yang benar-benar berlaku saat itu.
    """

    __tablename__ = "timbangan_tara_standar"
    __table_args__ = (
        Index(
            "ix_timbangan_tara_standar_berlaku",
            "supplier_id", "jenis_kode", "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    jenis_kode: Mapped[str] = mapped_column(String(30), nullable=False)

    jumlah_sampel: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_berat_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)
    tara_per_karung_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False)
    jenis_karung: Mapped[str | None] = mapped_column(String(60))

    berlaku_mulai: Mapped[date] = mapped_column(Date, nullable=False)
    berlaku_sampai: Mapped[date | None] = mapped_column(Date)
    # BERLAKU / DIGANTI / KEDALUWARSA
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="BERLAKU")

    alasan: Mapped[str | None] = mapped_column(Text)
    dibuat_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    disetujui_oleh_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_akun.id")
    )
    disetujui_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ══════════════════════════════════════════════════════════════════════════
# Transaksi
# ══════════════════════════════════════════════════════════════════════════

class TimbanganTransaksi(Base, TimestampMixin):
    """Satu kedatangan armada = satu transaksi timbang.

    Angka timbangan disimpan APA ADANYA. Kolom hasil adalah SNAPSHOT hitungan
    saat disimpan, dan `aturan_snapshot` menyimpan aturan yang dipakai — supaya
    laporan lama tidak berubah bila ambang direvisi kemudian.

    Dua kali timbang bisa dilakukan orang yang berbeda; keduanya dicatat.
    Petugas timbang yang tertera pada bukti adalah petugas timbang KEDUA.
    """

    __tablename__ = "timbangan_transaksi"
    __table_args__ = (
        Index("ix_timbangan_transaksi_tanggal_supplier", "tanggal", "supplier_id"),
        Index("ix_timbangan_transaksi_tiket", "status_tiket", "tanggal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Dibentuk di perangkat: TRX-YYYYMMDD-<perangkat>-<urutan>
    kode: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    # Mengikuti tanggal timbang KEDUA (transaksi bisa melewati tengah malam).
    tanggal: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # MASUK / KELUAR / BEBAS
    arah: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    jenis_kode: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    cara_timbang: Mapped[str] = mapped_column(
        String(12), nullable=False, default=CARA_DUA_KALI
    )
    # Salinan aturan yang dipakai (JSON) — butir b.
    aturan_snapshot: Mapped[str | None] = mapped_column(Text)

    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    # Untuk jasa timbang: pihak tidak selalu terdaftar sebagai supplier.
    pihak_nama: Mapped[str | None] = mapped_column(String(120))
    kendaraan_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_kendaraan.id")
    )
    nomor_polisi: Mapped[str | None] = mapped_column(String(20), index=True)
    nama_sopir: Mapped[str | None] = mapped_column(String(100))

    # ── Timbang pertama ──
    timbang1_kg: Mapped[float] = mapped_column(KG, nullable=False)
    timbang1_waktu: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timbang1_waktu_sistem: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    timbang1_petugas_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_akun.id")
    )

    # ── Timbang kedua (kosong pada tiket yang masih terbuka) ──
    timbang2_kg: Mapped[float | None] = mapped_column(KG)
    timbang2_waktu: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timbang2_waktu_sistem: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    timbang2_petugas_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_akun.id")
    )

    # Diturunkan dari kedua angka di atas menurut arah, disimpan eksplisit
    # supaya laporan tidak perlu menebak mana yang bermuatan.
    berat_bermuatan_kg: Mapped[float | None] = mapped_column(KG)
    berat_kosong_kg: Mapped[float | None] = mapped_column(KG)
    tara_lain_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)

    # ── Snapshot hasil hitung ──
    netto_timbangan_kg: Mapped[float | None] = mapped_column(KG)
    jumlah_karung: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tara_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    berat_barang_kg: Mapped[float | None] = mapped_column(KG)
    berat_acuan_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    selisih_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    selisih_persen: Mapped[float] = mapped_column(PCT, nullable=False, default=0)
    batas_bawah_kg: Mapped[float | None] = mapped_column(KG)
    batas_atas_kg: Mapped[float | None] = mapped_column(KG)
    # NORMAL / PERLU_PEMERIKSAAN / INVESTIGASI / KURANG / KELEBIHAN / TANPA_KONTROL
    status_kontrol: Mapped[str | None] = mapped_column(String(24), index=True)
    keterangan: Mapped[str | None] = mapped_column(Text)

    # ── Siklus hidup ──
    status_tiket: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TIKET_TERBUKA, index=True
    )
    status_transaksi: Mapped[str] = mapped_column(
        String(10), nullable=False, default=TRX_AKTIF, index=True
    )
    tutup_paksa_alasan: Mapped[str | None] = mapped_column(Text)
    terkunci: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dikunci_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jumlah_revisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    void_alasan: Mapped[str | None] = mapped_column(Text)
    void_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    void_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catatan: Mapped[str | None] = mapped_column(Text)

    # ── Jejak perangkat & sinkronisasi ──
    perangkat_kode: Mapped[str | None] = mapped_column(String(8))
    dibuat_offline: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    dikirim_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dibuat_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    diubah_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))

    # ── Jembatan integrasi ke modul produksi (kosong sampai diaktifkan) ──
    # Gabah menaut memakai BERAT NOTA; PK memakai BERAT PK BERSIH.
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pk_purchase_batches.id")
    )

    kendaraan: Mapped["TimbanganKendaraan | None"] = relationship(lazy="selectin")
    muatan: Mapped[list["TimbanganMuatan"]] = relationship(
        back_populates="transaksi", lazy="selectin",
        cascade="all, delete-orphan", order_by="TimbanganMuatan.urutan",
    )
    foto: Mapped[list["TimbanganFoto"]] = relationship(
        back_populates="transaksi", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def aktif(self) -> bool:
        return self.status_transaksi == TRX_AKTIF

    @property
    def selesai(self) -> bool:
        return self.status_tiket in (TIKET_SELESAI, TIKET_DITUTUP_PAKSA)

    @property
    def petugas_bukti_id(self) -> int | None:
        """Petugas yang tertera pada bukti timbang: pelaku timbang TERAKHIR."""
        return self.timbang2_petugas_id or self.timbang1_petugas_id


class TimbanganMuatan(Base):
    """Baris muatan: satu untuk barang masuk, beberapa untuk pengiriman.

    Satu bentuk data untuk kedua arah — bukan dua skema berbeda.
    """

    __tablename__ = "timbangan_muatan"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"), nullable=False
    )
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    jenis_kode: Mapped[str] = mapped_column(String(30), nullable=False)

    # Nomor nota boleh kosong — supplier sering memakai nota tulis tangan.
    nomor_acuan: Mapped[str | None] = mapped_column(String(50), index=True)
    jumlah_karung: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tara_per_karung_kg: Mapped[float] = mapped_column(
        KG_KECIL, nullable=False, default=0
    )
    berat_acuan_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    # Baris tara standar yang dipakai, bila ada — agar bisa ditelusuri.
    tara_standar_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_tara_standar.id")
    )
    catatan: Mapped[str | None] = mapped_column(Text)

    transaksi: Mapped[TimbanganTransaksi] = relationship(back_populates="muatan")

    @property
    def tara_kg(self) -> float:
        return self.jumlah_karung * self.tara_per_karung_kg


class TimbanganPemeriksaan(Base, TimestampMixin):
    """Lembar pemeriksaan SOP butir 6 — enam langkah, dicatat per langkah.

    Transaksi yang perlu diperiksa boleh diselesaikan dengan catatan resolusi;
    yang penting jejaknya ada, bukan bahwa semuanya berakhir bersih.
    """

    __tablename__ = "timbangan_pemeriksaan"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id"), nullable=False, index=True
    )

    langkah_ulang_timbang: Mapped[str | None] = mapped_column(Text)
    langkah_hitung_karung: Mapped[str | None] = mapped_column(Text)
    langkah_periksa_tara: Mapped[str | None] = mapped_column(Text)
    langkah_periksa_dokumen: Mapped[str | None] = mapped_column(Text)
    langkah_periksa_muatan: Mapped[str | None] = mapped_column(Text)
    langkah_lapor: Mapped[str | None] = mapped_column(Text)

    dilaporkan_ke: Mapped[str | None] = mapped_column(String(120))
    dilaporkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # SELISIH_WAJAR / SALAH_CATAT / SUSUT_PERJALANAN / TARA_TIDAK_SESUAI /
    # DOKUMEN_TIDAK_SESUAI / PERLU_TINDAK_LANJUT / LAIN
    kategori_hasil: Mapped[str | None] = mapped_column(String(30), index=True)
    catatan_resolusi: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PEMERIKSAAN_DIBUKA, index=True
    )
    dibuka_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    ditutup_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    ditutup_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimbanganCetak(Base):
    """Riwayat cetak bukti timbang. Cetak ulang wajib beralasan."""

    __tablename__ = "timbangan_cetak"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id"), nullable=False, index=True
    )
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ulang: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alasan: Mapped[str | None] = mapped_column(Text)
    oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    waktu: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("transaksi_id", "urutan", name="uq_timbangan_cetak_urutan"),
    )


class TimbanganFoto(Base):
    """Foto bukti. Disimpan sebagai BLOB di Postgres — filesystem Railway
    bersifat sementara, bukti tidak boleh hilang saat deploy ulang."""

    __tablename__ = "timbangan_foto"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"), nullable=False
    )
    # ACUAN / TIMBANG_1 / TIMBANG_2 / MUATAN / LAIN
    jenis: Mapped[str] = mapped_column(String(20), nullable=False, default="LAIN")
    nama_file: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False, default="image/jpeg")
    ukuran_byte: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    konten: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    diunggah_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    transaksi: Mapped[TimbanganTransaksi] = relationship(back_populates="foto")


# ══════════════════════════════════════════════════════════════════════════
# Monitoring & audit
# ══════════════════════════════════════════════════════════════════════════

class TimbanganSkorSupplier(Base):
    """Cache skor monitoring pihak (dihitung ulang berkala/on-demand)."""

    __tablename__ = "timbangan_skor_supplier"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    # 'TERKINI' atau 'YYYY-MM'
    periode: Mapped[str] = mapped_column(String(10), nullable=False, default="TERKINI")
    skor_total: Mapped[float] = mapped_column(PCT, nullable=False, default=0)
    kategori: Mapped[str] = mapped_column(String(2), nullable=False, default="C")
    jumlah_transaksi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    komponen_json: Mapped[str | None] = mapped_column(Text)
    pola_json: Mapped[str | None] = mapped_column(Text)
    dihitung_pada: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "supplier_id", "periode", name="uq_timbangan_skor_supplier_periode"
        ),
    )


class TimbanganAudit(Base):
    """Jejak audit modul: siapa, kapan, aksi apa, nilai sebelum & sesudah.

    Hanya bertambah. Koreksi menulis baris baru, tidak pernah menimpa.
    """

    __tablename__ = "timbangan_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    waktu: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    akun_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    akun_nama: Mapped[str | None] = mapped_column(String(100))
    # LOGIN / LOGOUT / SIMPAN_TIMBANG_1 / SIMPAN_TIMBANG_2 / KOREKSI /
    # VOID / TUTUP_PAKSA / CETAK / PEMERIKSAAN / TARA_STANDAR / ...
    aksi: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entitas: Mapped[str | None] = mapped_column(String(40))
    entitas_id: Mapped[str | None] = mapped_column(String(40))
    ringkasan: Mapped[str | None] = mapped_column(Text)
    nilai_sebelum: Mapped[str | None] = mapped_column(Text)
    nilai_sesudah: Mapped[str | None] = mapped_column(Text)
    perangkat_kode: Mapped[str | None] = mapped_column(String(8))
    ip: Mapped[str | None] = mapped_column(String(45))
