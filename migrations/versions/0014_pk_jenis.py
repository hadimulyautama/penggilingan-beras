"""Jenis PK luar (ks/kl/campuran/semi_ks) di pk_purchase_batches

Revision ID: 0014_pk_jenis
Revises: 0013_kemasan_brand
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_pk_jenis"
down_revision: Union[str, None] = "0013_kemasan_brand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pk_purchase_batches",
        sa.Column("jenis_pk", sa.String(12)),
    )


def downgrade() -> None:
    op.drop_column("pk_purchase_batches", "jenis_pk")
