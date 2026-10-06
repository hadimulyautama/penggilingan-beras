"""Bekatul dicabut dari `hasil_ditahan` pesanan yang SUDAH berjalan.

PEMBALIKAN keputusan pemilik 12 (6 Oktober 2026): bekatul dulu otomatis
berubah kepemilikan jadi milik pabrik begitu dibukukan. Laporan lapangan —
operator packing bekatul dari proses jasa, lalu Stok Produk pabrik menuduh
"dibukukan melebihi hasil mesin" karena bekatulnya terhitung di dua tempat
yang tak saling kenal — membalik keputusan itu: bekatul sekarang mengikuti
pola broken/menir/reject, tetap milik pesanan sampai dipindah lewat tombol
"Pindah kepemilikan" (`pindah_kepemilikan_bekatul_curah`).

`Jasa.hasil_ditahan` adalah CUPLIKAN kesepakatan, disalin saat pesanan
dibuat — bukan dibaca ulang dari kode (lihat docstring kolomnya). Mengubah
`HASIL_DITAHAN_BAWAAN` saja (sudah dilakukan di kode) hanya berlaku untuk
pesanan BARU; pesanan yang sudah berjalan tetap membawa "sekam,bekatul" di
barisnya sendiri, dan bekatul BARU yang dibukukan di bawahnya akan tetap
otomatis jadi milik pabrik kalau baris itu tak ikut dibackfill.

Migrasi ini mencabut "bekatul" dari `hasil_ditahan` SELURUH baris `jasa` —
termasuk yang sudah `selesai`/`dibatalkan`, sebab kolom itu hanya dibaca
saat pesanan masih bisa menerima bekatul BARU (proses sosoh berjalan);
pesanan yang sudah tertutup tak pernah lagi dibukukan, jadi mengubahnya di
sana tak berakibat apa pun — mengecualikannya hanya menambah cabang kode
tanpa guna.

Penggantian STRING, bukan sekadar hapus substring "bekatul": menjaga
"sekam" dan koma tetap rapi (`"sekam,bekatul"` → `"sekam"`, bukan
`"sekam,"`), dan baris yang isinya cuma `"bekatul"` sendirian (kalau pernah
ada) jadi string kosong, bukan dibiarkan `NULL` (kolomnya `NOT NULL`).

⚠ TIDAK membetulkan baris stok (`byproduct_stock`/`finished_goods_stock`)
yang SUDAH terlanjur dibukukan `jasa_id NULL` dari proses jasa sebelum
pembalikan ini — itu data SATU KALI pada SATU basis data (produksi), bukan
transformasi yang berlaku di semua lingkungan, jadi dikerjakan lewat skrip
terpisah (dijalankan sekali via `railway ssh`), bukan migrasi. Lihat catatan
commit ini.

Revision ID: 0073_bekatul_bukan_ditahan
Revises: 0072_broken_ke_silo
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0073_bekatul_bukan_ditahan"
down_revision: Union[str, None] = "0072_broken_ke_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(r"""
        UPDATE jasa
           SET hasil_ditahan = btrim(
                 regexp_replace(',' || hasil_ditahan || ',', ',bekatul,', ',', 'g'),
                 ',')
         WHERE ',' || hasil_ditahan || ',' LIKE '%,bekatul,%'
    """)


def downgrade() -> None:
    # Tak dikembalikan: baris yang bekatulnya sudah terlanjur dipindah
    # (via "Pindah kepemilikan") sejak upgrade ini tak bisa dibedakan dari
    # baris yang memang belum pernah punya bekatul — menambahkan kembali
    # "bekatul" ke SEMUA baris akan menahan bekatul BARU yang semestinya
    # tetap milik pesanan. Downgrade skema (tabel/kolom) tidak terpengaruh;
    # yang tak bisa mundur murni data perilaku bisnis.
    pass
