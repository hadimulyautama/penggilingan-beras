"""Dua sisa selisih model ↔ basis data pada tabel master.

Temuan QA X-19, 11 September 2026 — bagian terakhirnya.

1. `pelanggan.deleted_at` bertipe `timestamp` TANPA zona, sedangkan
   `suppliers.deleted_at` bertipe `timestamptz`. Dua kolom yang artinya sama
   persis, dengan bentuk berbeda, pada tabel yang dibangun migrasi yang sama.
   Yang membacanya lewat ORM mendapat satu datetime berzona dan satu tidak,
   dan perbandingan antara keduanya melempar TypeError — di tempat yang
   berbeda-beda, tergantung pemasok atau pelanggan yang kebetulan dihapus.

2. `ix_users_telegram_user_id` berdiri di samping constraint unik
   `users_telegram_user_id_key` pada kolom yang sama. Constraint unik sudah
   berindeks, jadi yang satu ini murni duplikat: memakan ruang, melambatkan
   setiap tulis ke `users`, dan membuat `alembic check` mengusulkan menukar
   keduanya tiap kali dijalankan.

Sesudah migrasi ini, `alembic check` pada chain produksi BERSIH — dan karena
itu ia bisa dijadikan penjaga sungguhan di CI, bukan sekadar laporan.

Revision ID: 0044_tipe_dan_indeks_master
Revises: 0043_selaraskan_not_null
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0044_tipe_dan_indeks_master"
down_revision: Union[str, None] = "0043_selaraskan_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nilai yang sudah ada ditafsirkan sebagai waktu Jakarta — itulah zona
    # yang dipakai seluruh aplikasi saat menulisnya. Tanpa `USING`, Postgres
    # menganggapnya UTC dan setiap cap waktu bergeser tujuh jam.
    op.execute(
        "ALTER TABLE pelanggan ALTER COLUMN deleted_at "
        "TYPE timestamptz USING deleted_at AT TIME ZONE 'Asia/Jakarta'"
    )
    op.execute("DROP INDEX IF EXISTS ix_users_telegram_user_id")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE pelanggan ALTER COLUMN deleted_at "
        "TYPE timestamp USING deleted_at AT TIME ZONE 'Asia/Jakarta'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_telegram_user_id "
        "ON users (telegram_user_id)"
    )
