"""Bobot batch boleh KOSONG (menunggu) — referensi bobot = tiket timbang.

Batch bisa dibuat saat bongkar walau bobot belum ada (nota kosong & timbang-2 belum).
`berat_total_kg` jadi nullable; diisi otomatis (disinkron) dari tiket saat bobot tersedia
(nota atau netto timbang). `sumber_berat='menunggu'` selama kosong. HPP/stok mengecualikan
yang masih kosong.

Revision ID: 0028_batch_bobot_nullable
Revises: 0027_intake_timbangan_link
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_batch_bobot_nullable"
down_revision: Union[str, None] = "0027_intake_timbangan_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("purchase_batches", "pk_purchase_batches")


def upgrade() -> None:
    for t in _TABLES:
        op.alter_column(t, "berat_total_kg",
                        existing_type=sa.Numeric(12, 2), nullable=True)


def downgrade() -> None:
    # Kembalikan NOT NULL: isi dulu yang NULL dengan 0 agar tak menolak.
    for t in _TABLES:
        op.execute(f"UPDATE {t} SET berat_total_kg = 0 WHERE berat_total_kg IS NULL")
        op.alter_column(t, "berat_total_kg",
                        existing_type=sa.Numeric(12, 2), nullable=False)
