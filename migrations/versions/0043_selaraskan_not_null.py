"""Basis data menegakkan apa yang sudah dijanjikan model: 33 kolom NOT NULL.

Temuan QA X-19, 11 September 2026.

Tiga puluh tiga kolom dinyatakan NOT NULL di model tetapi mengizinkan NULL di
basis data. Selisih itu tak pernah terlihat karena semuanya punya
`server_default`, jadi NULL hanya masuk bila seseorang menulisnya dengan
sengaja — lewat SQL mentah, lewat aplikasi lain yang berbagi basis data ini,
atau lewat migrasi yang menambah kolom pada tabel yang sudah berisi.

Yang membuatnya berbahaya bukan NULL-nya melainkan cara ia lolos: seluruh kode
membandingkan `status == "aktif"`, dan perbandingan dengan NULL selalu salah.
Jadi satu baris ber-status NULL tidak muncul di daftar aktif, tidak muncul di
daftar nonaktif, dan tidak muncul di laporan mana pun. Ia hilang dari
pandangan tanpa satu pesan galat pun.

Dua langkah, dan urutannya bukan pilihan:

  1. ISI dulu yang NULL dengan nilai bawaannya. `SET NOT NULL` pada kolom yang
     masih memuat NULL akan gagal, dan migrasi yang gagal di tengah
     meninggalkan sebagian kolom sudah ketat dan sebagian belum.
  2. Baru `SET NOT NULL`.

Tabel MASTER ikut (`users`, `suppliers`, `silos`, `dryers`): ketiga aplikasi
sudah memperlakukan kolom-kolom itu sebagai selalu terisi, jadi yang berubah
di sini hanyalah basis data akhirnya ikut mengatakannya.

Revision ID: 0043_selaraskan_not_null
Revises: 0042_indeks_panas
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0043_selaraskan_not_null"
down_revision: Union[str, None] = "0042_indeks_panas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (tabel, kolom, nilai pengisi untuk baris yang NULL).
#:
#: Nilai pengisinya SAMA dengan `server_default` kolomnya di basis data, yang
#: juga sama dengan `default` di model — ketiganya memang menyatakan hal yang
#: sama, dan itulah yang membuat pengisian ini aman: baris yang NULL adalah
#: baris yang seharusnya tak pernah ada.
KOLOM = [
    ("brands", "tipe", "'house'"),
    ("brands", "aktif", "true"),
    ("package_sizes", "aktif", "true"),
    ("packaging_materials", "aktif", "true"),
    ("rice_quality_standards", "urutan", "0"),
    ("rice_quality_standards", "aktif", "true"),
    ("suppliers", "status", "'aktif'"),
    ("dryers", "status", "'aktif'"),
    ("product_skus", "aktif", "true"),
    ("silos", "status", "'kosong'"),
    ("users", "access_level", "'operational'"),
    ("users", "wa_broadcast_opt_in", "false"),
    ("users", "status", "'aktif'"),
    ("byproduct_stock", "status", "'tersedia'"),
    ("drying_lots", "status", "'proses'"),
    ("notifications", "prioritas", "'kuning'"),
    ("notifications", "status", "'baru'"),
    ("notifications", "eskalasi_jam", "24"),
    ("notifications", "status_eskalasi", "'belum'"),
    ("pk_purchase_batches", "status_batch", "'baru'"),
    ("pk_purchase_batches", "flag_unverified", "true"),
    ("polishing_process", "status", "'proses'"),
    ("purchase_batches", "status_batch", "'baru'"),
    ("purchase_batches", "flag_unverified", "true"),
    ("pk_purchase_verifications", "status_verifikasi", "'terverifikasi'"),
    # Dua ini tak punya server_default; yang NULL diisi waktu sekarang.
    # Cap waktu yang hilang lebih baik diisi "kapan ini dibetulkan" daripada
    # ditebak mundur — tebakan mundur terbaca sebagai fakta.
    ("pk_rejections", "created_at", "now()"),
    ("pk_rejections", "updated_at", "now()"),
    ("purchase_batch_verifications", "status_verifikasi", "'terverifikasi'"),
    ("silo_storage", "status", "'terisi'"),
    ("milling_process", "status", "'proses'"),
    ("internal_transfers", "status", "'terkirim'"),
    ("milling_process_verifications", "status_verifikasi", "'terverifikasi'"),
    ("pk_gudang2_intakes", "flag_hpp_belum_tersedia", "true"),
]


def upgrade() -> None:
    for tabel, kolom, isi in KOLOM:
        op.execute(
            f"UPDATE {tabel} SET {kolom} = {isi} WHERE {kolom} IS NULL")
        op.execute(
            f"ALTER TABLE {tabel} ALTER COLUMN {kolom} SET NOT NULL")


def downgrade() -> None:
    # Dilonggarkan lagi, tetapi nilainya TIDAK dikembalikan jadi NULL: yang
    # sudah terisi memang seharusnya terisi sejak awal.
    for tabel, kolom, _isi in KOLOM:
        op.execute(f"ALTER TABLE {tabel} ALTER COLUMN {kolom} DROP NOT NULL")
