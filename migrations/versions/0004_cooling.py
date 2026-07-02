"""Log pendinginan gabah (setelah pengeringan, gabah tetap di dryer)

Revision ID: 0004_cooling
Revises: 0003_dryers
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_cooling"
down_revision: Union[str, None] = "0003_dryers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drying_cooling_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id"), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("catatan", sa.String(255)),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("drying_cooling_logs")
