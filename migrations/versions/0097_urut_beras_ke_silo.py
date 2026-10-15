"""Selaraskan penghitung kode BRS dengan perpindahan yang sudah ada.

Tabel beras_ke_silo dibuat setelah migrasi awal kode_urut, jadi kode BRS lama
tidak ikut masuk ke penghitung atomik. Tanpa backfill, perpindahan berikutnya
bisa mencoba memakai kembali kode BRS yang sudah tersimpan dan gagal saat commit.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0097_urut_beras_ke_silo"
down_revision: Union[str, None] = "0096_sumber_beras_ke_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO kode_urut (awalan, tanggal, n)
        SELECT 'BRS', to_date(split_part(kode_pindah, '-', 2), 'YYYYMMDD'),
               max(CAST(split_part(kode_pindah, '-', 3) AS integer))
          FROM beras_ke_silo
         WHERE kode_pindah ~ '^BRS-[0-9]{8}-[0-9]+$'
         GROUP BY 1, 2
        ON CONFLICT (awalan, tanggal)
        DO UPDATE SET n = greatest(kode_urut.n, EXCLUDED.n)
    """))


def downgrade() -> None:
    # Backfill penghitung tidak dibatalkan: baris mungkin sudah dipakai untuk
    # menerbitkan kode setelah migrasi berjalan.
    pass
