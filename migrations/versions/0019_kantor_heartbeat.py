"""Denyut hidup bot untuk deteksi downtime (kantor_heartbeat)

Revision ID: 0019_kantor_heartbeat
Revises: 0018_kantor_aturan_email
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_kantor_heartbeat"
down_revision: Union[str, None] = "0018_kantor_aturan_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kantor_heartbeat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_alive", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("kantor_heartbeat")
