"""Mesin pengering sebagai sumber daya (kapasitas) + seed 1 dryer G1

Revision ID: 0003_dryers
Revises: 0002_milling
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_dryers"
down_revision: Union[str, None] = "0002_milling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dryers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("warehouse_id", sa.Integer, sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("nama", sa.String(50), nullable=False),
        sa.Column("kapasitas_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), server_default="aktif"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("drying_lots", sa.Column("dryer_id", sa.Integer, sa.ForeignKey("dryers.id")))

    # Seed satu mesin pengering Gudang 1 (kapasitas 35 ton).
    op.execute(
        """
        INSERT INTO dryers (warehouse_id, nama, kapasitas_kg, status)
        SELECT id, 'Pengering 1', 35000, 'aktif'
        FROM warehouses
        WHERE nama_gudang LIKE 'Gudang 1%'
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_column("drying_lots", "dryer_id")
    op.drop_table("dryers")
