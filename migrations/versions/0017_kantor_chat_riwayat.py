"""Ingatan percakapan bot Kantor (kantor_chat_riwayat)

Revision ID: 0017_kantor_chat_riwayat
Revises: 0016_kantor
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_kantor_chat_riwayat"
down_revision: Union[str, None] = "0016_kantor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kantor_chat_riwayat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("peran", sa.String(12), nullable=False),
        sa.Column("isi", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_kantor_chat_riwayat_telegram_user_id",
        "kantor_chat_riwayat",
        ["telegram_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_kantor_chat_riwayat_telegram_user_id", table_name="kantor_chat_riwayat")
    op.drop_table("kantor_chat_riwayat")
