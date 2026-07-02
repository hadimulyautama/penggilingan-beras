"""Fase 1 lanjutan — Milling (Pecah Kulit) Gudang 1: 6 tabel

Revision ID: 0002_milling
Revises: 0001_phase1
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_milling"
down_revision: Union[str, None] = "0001_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "milling_process",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_proses", sa.String(20), nullable=False, unique=True),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("silo_storage_id", sa.Integer, sa.ForeignKey("silo_storage.id")),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id")),
        sa.Column("purchase_batch_id", sa.Integer, sa.ForeignKey("purchase_batches.id")),
        sa.Column("berat_gabah_masuk_kg", sa.Numeric(12, 2)),
        sa.Column("waktu_mulai", sa.DateTime(timezone=True), nullable=False),
        sa.Column("waktu_selesai", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), server_default="proses"),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "milling_progress_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("waktu_update", sa.DateTime(timezone=True), nullable=False),
        sa.Column("berat_kumulatif_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_table(
        "milling_pk_routing",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tujuan", sa.String(20), nullable=False),
        sa.Column("status_transfer", sa.String(20)),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_table(
        "milling_qc_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("kadar_air", sa.Numeric(5, 2)),
        sa.Column("broken_persen", sa.Numeric(5, 2)),
        sa.Column("susut_persen", sa.Numeric(5, 2)),
        sa.Column("kondisi", sa.String(10)),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_table(
        "milling_process_verifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id"), nullable=False, unique=True),
        sa.Column("berat_output_final_kg", sa.Numeric(12, 2)),
        sa.Column("verified_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("waktu_verifikasi", sa.DateTime(timezone=True)),
        sa.Column("status_verifikasi", sa.String(20), server_default="terverifikasi"),
        *_timestamps(),
    )
    op.create_table(
        "pk_stock_gudang1",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id")),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), server_default="0"),
        sa.Column("status", sa.String(20), server_default="tersedia"),
        *_timestamps(),
    )


def downgrade() -> None:
    for tbl in [
        "pk_stock_gudang1",
        "milling_process_verifications",
        "milling_qc_logs",
        "milling_pk_routing",
        "milling_progress_logs",
        "milling_process",
    ]:
        op.drop_table(tbl)
