"""Gudang 2 — penyosohan: polishing_process + silo_usage + output_logs

Revision ID: 0008_polishing
Revises: 0007_gudang2_intake
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_polishing"
down_revision: Union[str, None] = "0007_gudang2_intake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "polishing_process",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_proses", sa.String(20), nullable=False, unique=True),
        sa.Column("waktu_mulai", sa.DateTime(timezone=True), nullable=False),
        sa.Column("waktu_selesai", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), server_default="proses"),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "polishing_silo_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("polishing_process_id", sa.Integer, sa.ForeignKey("polishing_process.id"), nullable=False),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("berat_awal_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("berat_akhir_kg", sa.Numeric(12, 2)),
        sa.Column("berat_terpakai_kg", sa.Numeric(12, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "polishing_output_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("polishing_process_id", sa.Integer, sa.ForeignKey("polishing_process.id"), nullable=False),
        sa.Column("jenis", sa.String(20), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("waktu_update", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("polishing_output_logs")
    op.drop_table("polishing_silo_usage")
    op.drop_table("polishing_process")
