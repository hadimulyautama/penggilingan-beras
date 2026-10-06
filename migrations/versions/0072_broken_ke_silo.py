"""`broken_ke_silo` — pemindahan broken (byproduct_stock) ke silo broken.

Sebangun `pk_tumpukan_to_silo`: satu baris per pemindahan, sumbernya baris
`byproduct_stock` (broken yang sudah dicatat curah lewat `catat_broken`),
tujuannya silo ber-`jenis_isi='broken'`. `jasa_id` DISALIN dari sumbernya —
lihat docstring `BrokenKeSilo`. Keputusan pemilik 6 Oktober 2026.

Revision ID: 0072_broken_ke_silo
Revises: 0071_silo_jenis_isi
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0072_broken_ke_silo"
down_revision: Union[str, None] = "0071_silo_jenis_isi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broken_ke_silo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_pindah", sa.String(20), nullable=False, unique=True),
        sa.Column("byproduct_stock_id", sa.Integer,
                  sa.ForeignKey("byproduct_stock.id"), nullable=False),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jasa_id", sa.Integer, sa.ForeignKey("jasa.id")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("broken_ke_silo")
