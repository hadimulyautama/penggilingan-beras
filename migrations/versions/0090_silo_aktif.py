"""Tandai silo aktif agar silo kosong dapat diarsipkan tanpa merusak riwayat.

Revision ID: 0090_silo_aktif
Revises: 0089_silo_filter_komoditas
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0090_silo_aktif"
down_revision: Union[str, None] = "0089_silo_filter_komoditas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "silos",
        sa.Column("aktif", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("silos", "aktif")
