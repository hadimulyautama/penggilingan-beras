"""Simpan asal stok pada perpindahan beras ke silo.

Mendukung beras berkemasan dari tiket timbang dan retur selain hasil sosoh.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0096_sumber_beras_ke_silo"
down_revision: Union[str, None] = "0095_customer_returns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("beras_ke_silo", "polishing_process_id",
                    existing_type=sa.Integer(), nullable=True)
    op.add_column("beras_ke_silo", sa.Column("source_type", sa.String(20),
                                               nullable=True))
    op.add_column("beras_ke_silo", sa.Column("source_id", sa.Integer(),
                                               nullable=True))
    op.add_column("beras_ke_silo", sa.Column("product_sku_id", sa.Integer(),
                                               sa.ForeignKey("product_skus.id"),
                                               nullable=True))
    op.execute(
        "UPDATE beras_ke_silo SET source_type = 'polishing', "
        "source_id = polishing_process_id"
    )
    op.alter_column("beras_ke_silo", "source_type",
                    existing_type=sa.String(20), nullable=False,
                    server_default="polishing")
    op.create_index("ix_beras_ke_silo_source", "beras_ke_silo",
                    ["source_type", "source_id"])


def downgrade() -> None:
    bind = op.get_bind()
    direct_moves = bind.execute(sa.text(
        "SELECT count(*) FROM beras_ke_silo WHERE polishing_process_id IS NULL"
    )).scalar_one()
    if direct_moves:
        raise RuntimeError(
            "Tidak bisa downgrade: ada perpindahan beras dari stok timbang/retur "
            "yang tidak memiliki proses penyosohan."
        )
    op.drop_index("ix_beras_ke_silo_source", table_name="beras_ke_silo")
    op.drop_column("beras_ke_silo", "product_sku_id")
    op.drop_column("beras_ke_silo", "source_id")
    op.drop_column("beras_ke_silo", "source_type")
    op.alter_column("beras_ke_silo", "polishing_process_id",
                    existing_type=sa.Integer(), nullable=False)
