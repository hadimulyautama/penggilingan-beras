"""Pulihkan mutu pada stok beras lama dari proses asal yang tidak ambigu.

Baris barang jadi beras putih lama dapat memiliki standar mutu kosong,
meskipun proses penyosohan asalnya hanya menghasilkan satu grade beras.
Mutu dipulihkan hanya untuk proses dengan tepat satu jenis beras putih pada
catatan hasil. Proses yang menghasilkan beberapa grade dibiarkan agar tidak
menebak mutu stok.

Revision ID: 0085_mutu_stok_beras_lama
Revises: 0084_tutup_qc_gabah
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0085_mutu_stok_beras_lama"
down_revision: Union[str, None] = "0084_tutup_qc_gabah"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        WITH mutu_tunggal AS (
            SELECT polishing_process_id, MIN(jenis) AS jenis
              FROM polishing_output_logs
             WHERE jenis IN ('premium', 'medsuper', 'medium', 'sayur', 'beras_b')
             GROUP BY polishing_process_id
            HAVING COUNT(DISTINCT jenis) = 1
        )
        UPDATE finished_goods_stock AS stok
           SET rice_quality_standard_id = mutu.id
          FROM mutu_tunggal AS sumber,
               product_skus AS sku,
               rice_quality_standards AS mutu
         WHERE stok.source_type = 'polishing'
           AND stok.source_id = sumber.polishing_process_id
           AND stok.rice_quality_standard_id IS NULL
           AND sku.id = stok.product_sku_id
           AND sku.kategori = 'beras_putih'
           AND mutu.kode = sumber.jenis
    """)


def downgrade() -> None:
    # Perubahan data tidak dibalik agar mutu yang mungkin sudah dikoreksi
    # operator setelah migrasi tidak dihapus.
    pass
