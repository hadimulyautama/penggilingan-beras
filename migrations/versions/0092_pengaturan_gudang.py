"""Identitas stabil dan lokasi gudang.

Revision ID: 0092_pengaturan_gudang
Revises: 0091_target_kadar_air_per_dryer
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0092_pengaturan_gudang"
down_revision: Union[str, None] = "0091_target_kadar_air_per_dryer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("warehouses", sa.Column("kode_fungsi", sa.String(20), nullable=True))
    op.add_column("warehouses", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("warehouses", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("warehouses", sa.Column("aktif", sa.Boolean(), nullable=False,
                                           server_default=sa.true()))
    op.create_unique_constraint("uq_warehouses_kode_fungsi", "warehouses", ["kode_fungsi"])
    op.execute(sa.text("""
        UPDATE warehouses SET kode_fungsi = 'g1'
        WHERE lower(nama_gudang) LIKE 'gudang 1%'
    """))
    op.execute(sa.text("""
        UPDATE warehouses SET kode_fungsi = 'g2'
        WHERE lower(nama_gudang) LIKE 'gudang 2%'
    """))


def downgrade() -> None:
    op.drop_constraint("uq_warehouses_kode_fungsi", "warehouses", type_="unique")
    op.drop_column("warehouses", "aktif")
    op.drop_column("warehouses", "longitude")
    op.drop_column("warehouses", "latitude")
    op.drop_column("warehouses", "kode_fungsi")
