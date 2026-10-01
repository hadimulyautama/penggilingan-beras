"""Pesanan jasa — barang yang DITITIPKAN, bukan dibeli."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

#: Keadaan pesanan — tiga, dan hanya satu yang berjalan.
#:
#: SELESAI punya satu definisi, dan definisinya sengaja tidak memuat
#: "kedalaman": pernah ada barang masuk untuk pesanan ini, DAN tak ada lagi
#: barang ber-`jasa_id` ini di pabrik. Rancangan lama butuh syarat ganda
#: ("prosesnya selesai DAN sisanya nol") justru untuk menghindari jebakan nol —
#: sebelum apa pun terjadi, sisa juga nol. Dengan kedalaman yang dibaca dari
#: tempat barangnya, syaratnya jadi satu dan jebakannya hilang sendiri.
#:
#: Yang menghitungnya belum ada di irisan ini (`sisa_jasa()` menyusul bersama
#: layar Jasa dan notanya); kolom `status` sudah ada supaya pesanan bisa
#: ditutup dan dibatalkan tanpa migrasi kedua.
BERJALAN, SELESAI, DIBATALKAN = "berjalan", "selesai", "dibatalkan"

#: Hasil yang TIDAK kembali ke pelanggan, bawaan kesepakatan hari ini.
#:
#: Sekam karena tak terukur — keputusan pemilik: *"susut sekam tidak bisa
#: dideteksi, karena bisa saja masuk ke penyedot debu."* Bekatul karena
#: BERALIH MILIK: *"bekatul tidak kembali bukan berarti barangnya tidak boleh
#: keluar. bekatul otomatis berubah kepemilikan jadi milik kami. tetapi pemilik
#: barang juga harus tau hasil bekatul dari tiap proses barang miliknya."*
#:
#: Dipakai sebagai NILAI BAWAAN saat pesanan dibuat, lalu disalin ke barisnya.
#: Jangan dibaca ulang dari sini untuk pesanan lama — itu sebabnya kolomnya ada.
HASIL_DITAHAN_BAWAAN = "sekam,bekatul"


class Jasa(Base, TimestampMixin):
    """Satu pekerjaan jasa: barang satu pelanggan, satu kali kesepakatan.

    SATU PESANAN, BEBERAPA KEDATANGAN. Pak Budi menjasakan 24 ton dengan truk
    12 ton: dua tiket, dua batch, SATU pesanan. Kalau pesanannya lahir per
    tiket, satu pekerjaan terpecah jadi dua — dua nota, dua rendemen, dua
    hitungan sisa, semuanya salah — dan `pastikan_satu_jasa()` akan menolak
    menggiling keduanya bersama, benar menurut aturannya dan salah menurut
    kenyataannya. Tak perlu tabel penghubung: `purchase_batches.jasa_id` sudah
    N:1 dengan sendirinya, bentuk yang sama dengan `drying_lot_batches`.

    TIDAK ADA KOLOM `kedalaman`. Sampai mana pesanan diproses bukan fakta yang
    dinyatakan melainkan hasil yang terbaca dari di mana barangnya sekarang:
    masih ada batch ber-`jasa_id` → masih gabah; sudah ada lot giling → sudah
    PK; sudah ada proses sosoh → sudah beras; tak ada apa pun → sudah diambil.
    Keputusan pemilik 1 Oktober 2026, dan ia sejalan dengan watak app ini —
    mencatat apa yang TERJADI, bukan apa yang dijanjikan.

    TIDAK ADA KOLOM HARGA, TARIF, ATAU TOTAL. *"biaya adalah urusan keuangan.
    app timbangan dan operasional tidak mengurusi keuangan."* Kledo yang
    menagih. Kolom uang yang ditaruh "untuk nanti" adalah kolom yang akan diisi
    oleh orang yang tak tahu larangannya.

    SATU-SATUNYA BATASAN ADALAH KEPEMILIKAN: *"multi silo giling dan multi silo
    sosoh memungkinkan. yang tidak memungkinkan adalah menggabungkan barang
    jika kepemilikan berbeda. itu saja batasannya."* Tak ada batas minimum, tak
    ada batas ton, dan barang jasa tidak pernah ditolak. Barang SEPEMILIK boleh
    dicampur sebebas barang pabrik — lihat `app/services/jasa.py`.
    """

    __tablename__ = "jasa"
    __table_args__ = (
        # Dideklarasikan APA ADANYA seperti di basis data, termasuk syarat
        # parsialnya: indeks yang dibuat migrasi tanpa disebut di model membuat
        # `alembic check` mengusulkan MENGHAPUSNYA tiap kali dijalankan. Temuan
        # QA X-19, catatan panjangnya ada pada `PurchaseBatch`.
        Index("ix_jasa_pelanggan_berjalan", "pelanggan_id",
              postgresql_where=text("status = 'berjalan'"),
              sqlite_where=text("status = 'berjalan'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: JAS-YYMM-NNN, dari penghitung atomik `kode_urut` (bulanan, bukan harian:
    #: pesanan jasa datang beberapa dalam sebulan, bukan beberapa dalam sehari).
    kode: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    pelanggan_id: Mapped[int] = mapped_column(
        ForeignKey("pelanggan.id"), nullable=False)
    #: CUPLIKAN kesepakatan saat pesanan dibuat — BUKAN pembacaan kebijakan
    #: yang sedang berlaku.
    #:
    #: Kalau daftar ini dibaca dari kode setiap kali dibutuhkan, mengubah
    #: kebijakannya suatu hari akan mengubah arti SELURUH pesanan lama,
    #: termasuk yang notanya sudah dipegang pelanggan. Pola yang sama dan
    #: alasan yang sama sudah tertulis pada `MillingProcessSource.berat_kg`:
    #: *"disalin saat giling dimulai, bukan dihitung ulang belakangan"*.
    hasil_ditahan: Mapped[str] = mapped_column(
        Text, nullable=False, default=HASIL_DITAHAN_BAWAAN)
    #: 'berjalan' | 'selesai' | 'dibatalkan'
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=BERJALAN)
    catatan: Mapped[str | None] = mapped_column(Text)
    dibuat_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    #: Peristiwa yang melahirkan baris ini — `gabah_masuk` yang pertama untuk
    #: pesanan ini. Pesanan tidak punya peristiwanya sendiri: ia lahir sebagai
    #: akibat barang yang datang, dan peristiwa yang dicatat tanpa barang yang
    #: bergerak adalah baris buku besar yang tak menggerakkan apa pun.
    peristiwa_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("peristiwa.id"))
    #: Terisi = pesanannya dibatalkan. Berdampingan dengan `status`, dan itu
    #: disengaja: `status` yang dibaca layar, kolom ini KAPAN-nya. Pembacanya
    #: menyaring `status`, bukan kolom ini — tak ada saringan sesi otomatis di
    #: sini seperti pada tabel cermin, sebab `jasa` bukan cermin buku besar.
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
