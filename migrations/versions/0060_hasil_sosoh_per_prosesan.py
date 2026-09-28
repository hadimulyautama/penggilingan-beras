"""Hasil penyosohan: KUMULATIF → PER PROSESAN, berikut speknya.

Permintaan operator Gudang 2 (temuan lapangan 28 September 2026): dalam SATU
penyosohan mereka berganti spek, dan tiap spek punya hasilnya sendiri. Hari ini
angkanya kumulatif sepanjang proses, jadi untuk mencatat 200 kg broken yang
baru — sesudah 300 kg pada spek sebelumnya — operator harus mengetik 500. Angka
yang ia jumlah sendiri di kepala, tiap kali, sambil berdiri di mesin.

Keputusan pemilik pada pertanyaan QA: spek IKUT DICATAT pada tiap entri. Maka
kolomnya dua kerja sekaligus — `spek` lahir, dan arti `berat_kg` berubah dari
"total sejak awal" jadi "yang keluar pada prosesan ini".

⚠ BARIS LAMA IKUT DIUBAH, DAN INI BAGIAN YANG PALING BERBAHAYA BILA DILEWATI.

Baris lama kumulatif; baris baru bertambah. Membiarkan keduanya bercampur
membuat SELURUH Stok Produk salah tanpa satu pesan pun: pembacanya menjumlah,
dan jumlah atas baris kumulatif menghitung angka yang sama berkali-kali.
Contoh nyata: entri 300 lalu 500 (kumulatif, artinya 500 kg) akan terbaca 800.

Maka migrasi ini MENGUBAH BARIS LAMA jadi selisihnya, per (proses, jenis),
urut waktu lalu id — urutan yang sama yang dipakai `output_sosoh` untuk memilih
"baris terbaru". Jumlah seluruh selisih sama persis dengan kumulatif terakhir,
jadi tak ada satu kilogram pun yang berubah artinya.

Selisih NEGATIF dibiarkan apa adanya, tidak dinolkan: ia berarti angka
kumulatif pernah dikoreksi turun, dan koreksi itu bagian dari sejarah yang
sungguh terjadi. Menolkannya akan membuat jumlahnya melebihi kumulatif
terakhir — yaitu mengarang beras.

`downgrade` mengembalikan bentuk kumulatifnya dengan menjumlah berjalan.

Revision ID: 0060_hasil_sosoh_per_prosesan
Revises: 0059_berat_diminta
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_hasil_sosoh_per_prosesan"
down_revision: Union[str, None] = "0059_berat_diminta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Urutan yang SAMA dengan `stok.output_sosoh` sebelum migrasi ini — kalau
#: keduanya berbeda, selisihnya dihitung dari baris yang bukan pendahulunya.
_URUT = "ORDER BY waktu_update, id"


def upgrade() -> None:
    op.add_column("polishing_output_logs",
                  sa.Column("spek", sa.String(30), nullable=True))
    # Kumulatif → selisih. Dikerjakan SEKALI, dalam satu pernyataan, supaya tak
    # ada keadaan setengah yang bisa dibaca aplikasi di tengah jalan.
    op.execute(f"""
        WITH d AS (
            SELECT id,
                   berat_kg - COALESCE(LAG(berat_kg) OVER (
                       PARTITION BY polishing_process_id, jenis {_URUT}
                   ), 0) AS selisih
              FROM polishing_output_logs
        )
        UPDATE polishing_output_logs o
           SET berat_kg = d.selisih
          FROM d
         WHERE d.id = o.id
    """)


def downgrade() -> None:
    op.execute(f"""
        WITH k AS (
            SELECT id,
                   SUM(berat_kg) OVER (
                       PARTITION BY polishing_process_id, jenis {_URUT}
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS kumulatif
              FROM polishing_output_logs
        )
        UPDATE polishing_output_logs o
           SET berat_kg = k.kumulatif
          FROM k
         WHERE k.id = o.id
    """)
    op.drop_column("polishing_output_logs", "spek")
