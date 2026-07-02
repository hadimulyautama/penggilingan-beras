"""Log pemindahan gabah dari dryer ke silo (kondisional)

Revision ID: 0006_moving
Revises: 0005_transfer
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_moving"
down_revision: Union[str, None] = "0005_transfer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "silo_moving_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id")),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id")),
        sa.Column("tipe", sa.String(10), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("catatan", sa.String(255)),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("silo_moving_logs")
