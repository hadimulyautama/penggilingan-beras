"""Pembeli barang keluar MENUNJUK pelanggan Kledo, bukan cuma nama yang diketik.

Permintaan pemilik 29 September 2026: "nama pembeli di barang keluar
sinkronkan dengan pelanggan di kledo".

⭐ TAK ADA TABEL PELANGGAN BARU, dan itu bukan penghematan — `pelanggan` sudah
ada sejak migrasi 0029, sudah bertuliskan `kledo_contact_id`, dan sudah
DISEGARKAN DARI KLEDO sekali seminggu oleh layanan Kantor (`type_id = 3`,
diperiksa pada data sungguhan 1 September 2026). Yang belum ada cuma
TAUTANNYA: perintah barang keluar menyimpan nama pembeli sebagai teks bebas,
jadi satu pembeli bisa tertulis "Toko Makmur", "toko makmur", dan "TK Makmur"
dalam sepekan, dan tak satu pun laporan bisa menjumlahkannya.

DUA KOLOM BERDAMPINGAN, bukan satu — pola yang sama dengan
`berat_perintah_kg` di sebelah `berat_kg`, dan alasannya sejenis:

  · `pelanggan_id` adalah TAUTANNYA. Dengan ini "beras yang keluar ke pembeli
    ini" jadi pertanyaan yang punya jawaban tunggal, dan kelak bisa dicocokkan
    dengan faktur Kledo tanpa mencocokkan ejaan;
  · `nama_pembeli` yang sudah ada TETAP DIISI, dan itu bukan kelebihan data.
    Ia CUPLIKAN nama pada hari truk itu berangkat. Kledo tidak punya "merge":
    yang dilakukan orang ketika ada kontak ganda adalah memindahkan
    transaksinya lalu MENGHAPUS yang ganda (611 kontak dirapikan begitu). Surat
    jalan tahun lalu harus tetap bisa menyebut pembelinya meski barisnya sudah
    tidak ada di Kledo.

BOLEH KOSONG, dan ini keputusan yang disengaja. Penyegaran kontaknya MINGGUAN,
jadi pembeli yang dibuat di Kledo pagi ini bisa belum muncul di daftar. Kalau
tautannya diwajibkan, truk berhenti di halaman menunggu keuangan membuat
kontak — harga yang tak sepadan untuk sebuah daftar nama. Borangnya karena itu
tetap menerima nama yang diketik, dan barisnya lahir tanpa tautan.

BARIS LAMA TIDAK DITEBAK. Menyamakan `nama_pembeli` lama dengan
`nama_pelanggan` yang ejaannya kebetulan sama akan membuat kolom ini berarti
dua hal berbeda: "Admin memilih pembeli ini dari daftar" untuk baris baru, dan
"ejaannya cocok" untuk baris lama. Yang kedua bukan bukti, dan laporan yang
memakai keduanya sebagai satu hal akan salah tanpa bisa ditelusuri.

Revision ID: 0062_pembeli_dari_kledo
Revises: 0061_barang_keluar_berperintah
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0062_pembeli_dari_kledo"
down_revision: Union[str, None] = "0061_barang_keluar_berperintah"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outgoing_records", sa.Column(
        "pelanggan_id", sa.Integer(), sa.ForeignKey("pelanggan.id"),
        nullable=True))
    # Dibaca per pelanggan ("apa saja yang pernah keluar ke pembeli ini"), dan
    # itu pembacaan yang akan tumbuh — tabelnya bertambah satu baris per truk.
    op.create_index("ix_outgoing_records_pelanggan_id", "outgoing_records",
                    ["pelanggan_id"])


def downgrade() -> None:
    op.drop_index("ix_outgoing_records_pelanggan_id",
                  table_name="outgoing_records")
    op.drop_column("outgoing_records", "pelanggan_id")
