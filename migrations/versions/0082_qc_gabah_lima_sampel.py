"""QC gabah per truk dengan lima sampel dan dua pembacaan kadar air.

Revision ID: 0082_qc_gabah_lima_sampel
Revises: 0081_bekatul_jasa
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0082_qc_gabah_lima_sampel"
down_revision: Union[str, None] = "0081_bekatul_jasa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_batch_qc",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_batch_id", sa.Integer(), nullable=False),
        sa.Column("lamur", sa.Boolean(), nullable=True),
        sa.Column("jumlah_sak_lamur", sa.Integer(), nullable=True),
        sa.Column("biji_hijau", sa.String(20), nullable=False),
        sa.Column("densiti", sa.String(10), nullable=False),
        sa.Column("input_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["purchase_batch_id"], ["purchase_batches.id"]),
        sa.ForeignKeyConstraint(["input_by"], ["users.id"]),
        sa.UniqueConstraint("purchase_batch_id"),
        sa.CheckConstraint("jumlah_sak_lamur IS NULL OR jumlah_sak_lamur >= 0",
                            name="ck_purchase_batch_qc_sak_nonnegatif"),
        sa.CheckConstraint("biji_hijau IN ('hampir_tidak_ada', 'sedikit', 'sedang', 'banyak')",
                            name="ck_purchase_batch_qc_biji_hijau"),
        sa.CheckConstraint("densiti IN ('padat', 'sedang', 'empuk')",
                            name="ck_purchase_batch_qc_densiti"),
    )
    op.create_table(
        "purchase_batch_qc_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_batch_qc_id", sa.Integer(), nullable=False),
        sa.Column("nomor_sampel", sa.Integer(), nullable=False),
        sa.Column("kadar_air_1", sa.Numeric(5, 2), nullable=False),
        sa.Column("kadar_air_2", sa.Numeric(5, 2), nullable=False),
        sa.ForeignKeyConstraint(["purchase_batch_qc_id"],
                                ["purchase_batch_qc.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("purchase_batch_qc_id", "nomor_sampel",
                            name="uq_purchase_batch_qc_sample_no"),
        sa.CheckConstraint("nomor_sampel BETWEEN 1 AND 5",
                            name="ck_purchase_batch_qc_sample_no"),
        sa.CheckConstraint("kadar_air_1 BETWEEN 0 AND 100 AND kadar_air_2 BETWEEN 0 AND 100",
                            name="ck_purchase_batch_qc_sample_air_range"),
    )


def downgrade() -> None:
    op.drop_table("purchase_batch_qc_samples")
    op.drop_table("purchase_batch_qc")
