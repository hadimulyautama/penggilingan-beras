"""Barang keluar jadi berperintah: Admin memerintah, operator memuat, Admin verifikasi.

Permintaan pemilik 28 September 2026: "kita butuh satu halaman untuk transaksi
barang keluar. 1 transaksi bisa beberapa macam barang yang keluar. admin yang
bisa membuat perintah barang keluar, operator menerima tugas. lalu kembali
diverifikasi oleh admin saat selesai. dan transaksi barang keluar harus
terkoneksi dengan kode timbang barang keluar."

⭐ TAK ADA TABEL BARU, dan itu bukan penghematan — `outgoing_records` (1) ──
(N) `outgoing_items` memang sudah satu-ke-banyak sejak awal, berikut seluruh
kepala surat jalannya (pembeli, metode, no polisi, ekspedisi). Yang tak pernah
ada cuma KEADAAN-nya: barisnya lahir langsung "sudah terjadi", tanpa perintah,
tanpa tugas, tanpa verifikasi. Tabel baru untuk hal yang sudah bertabel akan
melahirkan dua sumber kebenaran tentang satu truk.

Yang ditambahkan tiga rombongan:

1. KEADAAN & SIAPA-KAPAN. `status` berjalan
   perintah → dimuat → selesai, dengan `batal` di sampingnya. Tiga pasang
   (oleh, waktu) disimpan TERPISAH, bukan satu kolom "terakhir diubah oleh":
   yang memerintah, yang memuat, dan yang memverifikasi adalah tiga orang
   berbeda dengan tiga tanggung jawab berbeda, dan menimpanya jadi satu kolom
   menghapus justru pertanyaan yang kelak ditanyakan.

2. DUA ANGKA BERDAMPINGAN di `outgoing_items` — `berat_perintah_kg` &
   `jumlah_karung_perintah` milik Admin, di sebelah `berat_kg` &
   `jumlah_karung` yang sudah ada dan kini berarti YANG BENAR-BENAR DIMUAT.
   Pelajaran yang sudah dibayar mahal di rantai permintaan PK: selisih yang
   ditimpa berhenti jadi pertanyaan. Muatan sungguhan memang berselisih dari
   perintahnya, dan selisih itu yang dilihat Admin saat verifikasi.

   ⚠ `berat_kg` LAMA TIDAK DIUBAH ARTINYA untuk baris lama: ia memang selalu
   berarti "yang keluar". Yang lahir cuma pasangan perintahnya, dan ia NULL
   pada baris lama — sebab barang yang sudah keluar sebelum hari ini memang
   tak pernah punya perintah, dan mengarang angkanya berarti menulis sejarah
   yang tak pernah terjadi.

3. TAUT TIMBANGAN. `timbangan_transaksi_id` → tiket `arah='KELUAR'`.

   ⚠ URUTAN WAKTUNYA TERBALIK DARI SISI MASUK, dan ini yang paling mudah
   salah. Truk masuk KOSONG, dimuat, lalu ditimbang bermuatan saat keluar —
   jadi tiketnya baru lengkap SESUDAH barangnya dimuat. Ia karenanya NULL
   sampai langkah verifikasi, dan tak boleh dijadikan syarat di langkah mana
   pun sebelumnya. Sisi masuk justru dimulai dari tiketnya; menirunya
   mentah-mentah di sini akan membuat perintah tak bisa dibuat sebelum truknya
   datang.

INDEKSNYA PARSIAL, bukan unik biasa — satu tiket satu transaksi yang HIDUP.
Unik polos akan mengunci tiket itu selamanya begitu satu transaksi dibatalkan,
dan koreksinya jadi mustahil: truk yang salah dicatat tak punya jalan pulang.
Syaratnya `status <> 'batal'`, BUKAN `dibatalkan_pada IS NULL` seperti tabel
cermin — tabel ini memang punya kolom keadaan sendiri, dan menambah kolom
kedua yang berarti hal sama akan membuat keduanya bisa berselisih. `sqlite_where`
ikut ditulis sebab sebagian uji berjalan di sqlite; indeks yang cuma berdiri di
Postgres adalah pagar yang tak pernah diuji sampai ia dibutuhkan.

BARIS LAMA DIISI 'selesai'. Mereka memang sudah terjadi dan sudah tak menunggu
siapa pun; memberinya 'perintah' akan menerbitkan puluhan tugas palsu di layar
operator pada pagi pertama sesudah deploy.

Revision ID: 0061_barang_keluar_berperintah
Revises: 0060_hasil_sosoh_per_prosesan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0061_barang_keluar_berperintah"
down_revision: Union[str, None] = "0060_hasil_sosoh_per_prosesan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Dipakai indeks parsial DAN ditulis ulang di modelnya. Satu kalimat, dua
#: tempat — kalau keduanya berbeda, indeksnya berdiri atas syarat yang bukan
#: syarat yang dipercaya aplikasi.
_HIDUP = "status <> 'batal'"


def upgrade() -> None:
    op.add_column("outgoing_records", sa.Column(
        "status", sa.String(20), nullable=False, server_default="selesai"))
    for kolom, tipe in (
        ("diperintah_oleh", sa.Integer()),
        ("dimuat_oleh", sa.Integer()),
        ("diverifikasi_oleh", sa.Integer()),
        ("timbangan_transaksi_id", sa.Integer()),
    ):
        op.add_column("outgoing_records", sa.Column(kolom, tipe, nullable=True))
    for kolom in ("waktu_perintah", "waktu_muat", "waktu_verifikasi"):
        op.add_column("outgoing_records",
                      sa.Column(kolom, sa.DateTime(timezone=True), nullable=True))
    op.add_column("outgoing_records",
                  sa.Column("catatan_perintah", sa.String(300), nullable=True))
    op.add_column("outgoing_records", sa.Column("sebab_batal", sa.String(300),
                                                nullable=True))

    op.add_column("outgoing_items",
                  sa.Column("berat_perintah_kg", sa.Numeric(12, 2), nullable=True))
    op.add_column("outgoing_items",
                  sa.Column("jumlah_karung_perintah", sa.Integer(), nullable=True))

    # Satu tiket timbang keluar, satu transaksi yang hidup.
    op.create_index(
        "uq_outgoing_records_timbangan_hidup", "outgoing_records",
        ["timbangan_transaksi_id"], unique=True,
        postgresql_where=sa.text(_HIDUP), sqlite_where=sa.text(_HIDUP))

    # Antrean operator & meja Admin dibaca dari `status` di tiap halaman.
    op.create_index("ix_outgoing_records_status", "outgoing_records", ["status"])


def downgrade() -> None:
    op.drop_index("ix_outgoing_records_status", table_name="outgoing_records")
    op.drop_index("uq_outgoing_records_timbangan_hidup",
                  table_name="outgoing_records")
    op.drop_column("outgoing_items", "jumlah_karung_perintah")
    op.drop_column("outgoing_items", "berat_perintah_kg")
    for kolom in ("sebab_batal", "catatan_perintah", "waktu_verifikasi",
                  "waktu_muat", "waktu_perintah", "timbangan_transaksi_id",
                  "diverifikasi_oleh", "dimuat_oleh", "diperintah_oleh",
                  "status"):
        op.drop_column("outgoing_records", kolom)
