"""Izinkan menutup QC gabah setelah minimal satu pencatatan.

Revision ID: 0084_tutup_qc_gabah
Revises: 0083_qc_gabah_lima_pencatatan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0084_tutup_qc_gabah"
down_revision: Union[str, None] = "0083_qc_gabah_lima_pencatatan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_batch_qc", sa.Column("ditutup_pada", sa.DateTime(timezone=True)))
    op.add_column("purchase_batch_qc", sa.Column("ditutup_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_purchase_batch_qc_ditutup_by_users",
                          "purchase_batch_qc", "users", ["ditutup_by"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_purchase_batch_qc_ditutup_by_users",
                       "purchase_batch_qc", type_="foreignkey")
    op.drop_column("purchase_batch_qc", "ditutup_by")
    op.drop_column("purchase_batch_qc", "ditutup_pada")
