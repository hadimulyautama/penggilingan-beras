"""Transfer internal Gudang 1 -> Gudang 2

Revision ID: 0005_transfer
Revises: 0004_cooling
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_transfer"
down_revision: Union[str, None] = "0004_cooling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "internal_transfers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_transfer", sa.String(20), nullable=False, unique=True),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id")),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("lokasi_tujuan", sa.String(20), nullable=False),
        sa.Column("hpp_per_kg", sa.Numeric(12, 2)),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), server_default="terkirim"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("internal_transfers")
