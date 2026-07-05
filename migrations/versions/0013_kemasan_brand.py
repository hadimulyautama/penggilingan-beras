"""Kemasan per-merk: brand_id di packaging_purchases & packaging_losses

Revision ID: 0013_kemasan_brand
Revises: 0012_pk_rejection_lab_qc
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_kemasan_brand"
down_revision: Union[str, None] = "0012_pk_rejection_lab_qc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "packaging_purchases",
        sa.Column("brand_id", sa.Integer, sa.ForeignKey("brands.id")),
    )
    op.add_column(
        "packaging_losses",
        sa.Column("brand_id", sa.Integer, sa.ForeignKey("brands.id")),
    )


def downgrade() -> None:
    op.drop_column("packaging_losses", "brand_id")
    op.drop_column("packaging_purchases", "brand_id")
