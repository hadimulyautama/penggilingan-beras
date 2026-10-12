"""Satu simpan QC adalah satu pencatatan lengkap; lima per truk.

Revision ID: 0083_qc_gabah_lima_pencatatan
Revises: 0082_qc_gabah_lima_sampel
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0083_qc_gabah_lima_pencatatan"
down_revision: Union[str, None] = "0082_qc_gabah_lima_sampel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_batch_qc_samples", sa.Column("lamur", sa.Boolean(), nullable=True))
    op.add_column("purchase_batch_qc_samples", sa.Column("jumlah_sak_lamur", sa.Integer(), nullable=True))
    op.add_column("purchase_batch_qc_samples", sa.Column("biji_hijau", sa.String(20), nullable=True))
    op.add_column("purchase_batch_qc_samples", sa.Column("densiti", sa.String(10), nullable=True))
    op.add_column("purchase_batch_qc_samples", sa.Column("input_by", sa.Integer(), nullable=True))
    op.add_column("purchase_batch_qc_samples", sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column("purchase_batch_qc_samples", sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))

    op.execute(sa.text("""
        UPDATE purchase_batch_qc_samples AS s
        SET lamur = q.lamur,
            jumlah_sak_lamur = q.jumlah_sak_lamur,
            biji_hijau = q.biji_hijau,
            densiti = q.densiti,
            input_by = q.input_by,
            created_at = q.created_at,
            updated_at = q.updated_at
        FROM purchase_batch_qc AS q
        WHERE q.id = s.purchase_batch_qc_id
    """))
    with op.batch_alter_table("purchase_batch_qc_samples") as batch_op:
        batch_op.alter_column("biji_hijau", nullable=False)
        batch_op.alter_column("densiti", nullable=False)
        batch_op.alter_column("input_by", nullable=False)
        batch_op.alter_column("created_at", nullable=False)
        batch_op.alter_column("updated_at", nullable=False)
        batch_op.create_foreign_key("fk_purchase_batch_qc_sample_input_by_users",
                                    "users", ["input_by"], ["id"])
        batch_op.create_check_constraint(
            "ck_purchase_batch_qc_sample_sak_nonnegatif",
            "jumlah_sak_lamur IS NULL OR jumlah_sak_lamur >= 0")
        batch_op.create_check_constraint(
            "ck_purchase_batch_qc_sample_biji_hijau",
            "biji_hijau IN ('hampir_tidak_ada', 'sedikit', 'sedang', 'banyak')")
        batch_op.create_check_constraint(
            "ck_purchase_batch_qc_sample_densiti",
            "densiti IN ('padat', 'sedang', 'empuk')")


def downgrade() -> None:
    with op.batch_alter_table("purchase_batch_qc_samples") as batch_op:
        batch_op.drop_constraint("ck_purchase_batch_qc_sample_densiti", type_="check")
        batch_op.drop_constraint("ck_purchase_batch_qc_sample_biji_hijau", type_="check")
        batch_op.drop_constraint("ck_purchase_batch_qc_sample_sak_nonnegatif", type_="check")
        batch_op.drop_constraint("fk_purchase_batch_qc_sample_input_by_users", type_="foreignkey")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.drop_column("input_by")
        batch_op.drop_column("densiti")
        batch_op.drop_column("biji_hijau")
        batch_op.drop_column("jumlah_sak_lamur")
        batch_op.drop_column("lamur")
