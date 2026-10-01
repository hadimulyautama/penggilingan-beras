"""Jasa sampai BERAS: rantai Gudang 2, dan PK dari luar.

Keputusan pemilik 1 Oktober 2026, ditegaskan ulang: jasa dari **gabah basah,
gabah kering, DAN beras PK** — ketiganya, bukan gabah kering saja. Migrasi 0064
membawa pemilik barang sampai PK di Gudang 1 lalu berhenti di penyosohan, sebab
`polishing_process` belum bisa memikul pemilik. Berkas ini membuka sisanya.

── LIMA TABEL, dan satu yang SENGAJA tidak ikut ──

    pk_purchase_batches      PK dari luar — barang titipan, bukan dibeli
    polishing_process        satu proses sosoh milik satu pemilik
    finished_goods_stock     beras yang keluar, milik pemiliknya
    byproduct_stock          menir/broken/reject kembali; bekatul TIDAK
    outgoing_records         pengambilan oleh pemiliknya

`pk_tumpukan_to_silo` TIDAK diberi kolom ini, dan itu keputusan rancangan
bukan kelalaian: pemindahan tumpukan→silo tidak memperkenalkan pemilik baru —
pemiliknya sudah ada di intake asalnya, dan `jasa.pemilik_silo_g2()` membacanya
dari sana. Kolom kedua yang berarti hal yang sama adalah kolom yang suatu hari
berselisih dengan yang pertama, dan yang berselisih di sini berarti dua jawaban
tentang milik siapa isi sebuah silo.

── BEKATUL: SATU KOLOM MEMIKUL DUA ARTI, DAN ITU HARUS DIPISAH ──

Keputusan pemilik 12: *"bekatul tidak kembali bukan berarti barangnya tidak
boleh keluar. bekatul otomatis berubah kepemilikan jadi milik kami. tetapi
pemilik barang juga harus tau hasil bekatul dari tiap proses barang miliknya."*

Jadi bekatul punya DUA fakta yang berpisah:

    MILIK  = pabrik          (siapa yang berhak menjualnya)
    ASAL   = JAS-2610-012    (dari proses barang siapa ia keluar)

`byproduct_stock.jasa_id` menjawab yang PERTAMA, dan untuk bekatul jawabannya
NULL — ia milik pabrik, masuk Stok Produk, boleh dijual lewat jalur yang sama
dengan bekatul lain. ⚠ JANGAN membuat penghalang apa pun untuknya.

Yang KEDUA tidak butuh kolom sama sekali: `byproduct_stock.source_id` sudah
menunjuk `polishing_process.id`, dan prosesnya kini punya `jasa_id`. Jadi
"berapa bekatul dari proses barang Pak Budi" terjawab tanpa satu kolom
tambahan — dan kuerinya sudah ada di `stok.py`, lengkap dengan komentar
*"rincian per proses"*.

Rancangan yang menyimpan keduanya di satu kolom akan menghilangkan salah
satunya: `jasa_id` terisi membuat bekatul jadi stok pelanggan yang tak boleh
dijual, dan `jasa_id` NULL tanpa jejak asal menghapus hak pemilik barang untuk
mengetahuinya — hak yang justru ditegaskan keputusan 12.

── `pk_purchase_batches.supplier_id` DIBUKA ──

Sama seperti `purchase_batches` di 0064: `CHECK` "tepat satu dari dua" —
dibeli ATAU dititipkan. Sampai migrasi ini, jalur PK luar untuk tiket jasa
DITOLAK terang-terangan (penjaga di `create_pk_purchase_dari_timbang`), justru
karena tak ada tempat menyimpan pemiliknya; penolakan itu dicabut sekarang.

⚠ Dan larangannya tetap: JANGAN memasukkan pelanggan ke `suppliers`. Jalur PK
luar berbunyi "tak ada supplier_id → cari atau buat dari nama pihak", dan itu
yang akan melahirkan pemasok palsu bernama pelanggan.

Revision ID: 0065_jasa_gudang2
Revises: 0064_jasa
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0065_jasa_gudang2"
down_revision: Union[str, None] = "0064_jasa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Tabel yang mendapat `jasa_id` di irisan ini — urutannya mengikuti aliran
#: barangnya: PK masuk dari luar → disosoh → jadi beras & hasil samping →
#: diambil pemiliknya.
TABEL_BERJASA = (
    "pk_purchase_batches",
    "polishing_process",
    "finished_goods_stock",
    "byproduct_stock",
    "outgoing_records",
)

CK_BELI_ATAU_JASA_PK = "ck_pk_purchase_batches_beli_atau_jasa"


def upgrade() -> None:
    sambung = op.get_bind()

    for tabel in TABEL_BERJASA:
        op.add_column(tabel, sa.Column(
            "jasa_id", sa.Integer(), sa.ForeignKey("jasa.id"), nullable=True))
        # PARSIAL — baris berpemilik segelintir di antara riwayat
        # bertahun-tahun baris pabrik. Pola yang sama dengan 0064.
        op.create_index(
            f"ix_{tabel}_jasa", tabel, ["jasa_id"],
            postgresql_where=sa.text("jasa_id IS NOT NULL"),
            sqlite_where=sa.text("jasa_id IS NOT NULL"))

    op.alter_column("pk_purchase_batches", "supplier_id", nullable=True,
                    existing_type=sa.Integer())
    if sambung.dialect.name != "sqlite":
        # SQLite tak bisa menambah CHECK pada tabel yang sudah ada. Postgres
        # tetap mendapatnya — lihat catatan yang sama di 0064.
        op.execute(
            f"ALTER TABLE pk_purchase_batches ADD CONSTRAINT {CK_BELI_ATAU_JASA_PK} "
            "CHECK ((supplier_id IS NOT NULL) <> (jasa_id IS NOT NULL))"
        )


def downgrade() -> None:
    sambung = op.get_bind()

    if sambung.dialect.name != "sqlite":
        op.execute("ALTER TABLE pk_purchase_batches DROP CONSTRAINT IF EXISTS "
                   + CK_BELI_ATAU_JASA_PK)
    # Gagal bila ada baris jasa yang tertinggal, dan itu BENAR: menjatuhkannya
    # diam-diam berarti membuang catatan barang milik orang lain.
    op.alter_column("pk_purchase_batches", "supplier_id", nullable=False,
                    existing_type=sa.Integer())

    for tabel in TABEL_BERJASA:
        op.drop_index(f"ix_{tabel}_jasa", table_name=tabel)
        op.drop_column(tabel, "jasa_id")
