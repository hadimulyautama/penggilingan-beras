"""Fase pendinginan otomatis: waktu_mulai/selesai_pendinginan di drying_lots

Revision ID: 0015_cooling_phase
Revises: 0014_pk_jenis
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_cooling_phase"
down_revision: Union[str, None] = "0014_pk_jenis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drying_lots", sa.Column("waktu_mulai_pendinginan", sa.DateTime(timezone=True)))
    op.add_column("drying_lots", sa.Column("waktu_selesai_pendinginan", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("drying_lots", "waktu_selesai_pendinginan")
    op.drop_column("drying_lots", "waktu_mulai_pendinginan")
