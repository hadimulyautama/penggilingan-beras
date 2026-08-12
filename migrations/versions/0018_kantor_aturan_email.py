"""Aturan pemilahan email yang diajarkan pemilik (kantor_aturan_email)

Revision ID: 0018_kantor_aturan_email
Revises: 0017_kantor_chat_riwayat
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_kantor_aturan_email"
down_revision: Union[str, None] = "0017_kantor_chat_riwayat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kantor_aturan_email",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jenis", sa.String(12), nullable=False, server_default="from"),
        sa.Column("cocok", sa.String(255), nullable=False),
        sa.Column("verdikt", sa.String(12), nullable=False),
        sa.Column("catatan", sa.String(255), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="aktif"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("kantor_aturan_email")
