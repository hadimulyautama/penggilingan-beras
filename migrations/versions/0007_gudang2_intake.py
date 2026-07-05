"""Gudang 2 — PK masuk: beli luar, intake ke silo/tumpukan, pindah tumpukan->silo

Revision ID: 0007_gudang2_intake
Revises: 0006_moving
Create Date: 2026-07-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_gudang2_intake"
down_revision: Union[str, None] = "0006_moving"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pk_purchase_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_batch", sa.String(20), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("berat_total_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("no_polisi_truk", sa.String(20)),
        sa.Column("kadar_air_awal_persen", sa.Numeric(5, 2)),
        sa.Column("tanggal_pembelian", sa.Date, nullable=False),
        sa.Column("waktu_pembelian", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status_batch", sa.String(20), server_default="baru"),
        sa.Column("flag_unverified", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "pk_purchase_verifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pk_purchase_batch_id", sa.Integer, sa.ForeignKey("pk_purchase_batches.id"), nullable=False, unique=True),
        sa.Column("kadar_air", sa.Numeric(5, 2)),
        sa.Column("broken_persen", sa.Numeric(5, 2)),
        sa.Column("keputusan", sa.String(10)),
        sa.Column("potongan_kg", sa.Numeric(12, 2)),
        sa.Column("potongan_alasan", sa.String(120)),
        sa.Column("harga_per_kg", sa.Numeric(12, 2)),
        sa.Column("total_biaya", sa.Numeric(16, 2)),
        sa.Column("metode_harga", sa.String(10)),
        sa.Column("verified_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("waktu_verifikasi", sa.DateTime(timezone=True)),
        sa.Column("status_verifikasi", sa.String(20), server_default="terverifikasi"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "pk_gudang2_intakes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sumber_tipe", sa.String(20), nullable=False),
        sa.Column("pk_purchase_batch_id", sa.Integer, sa.ForeignKey("pk_purchase_batches.id")),
        sa.Column("internal_transfer_id", sa.Integer, sa.ForeignKey("internal_transfers.id")),
        sa.Column("tujuan", sa.String(20), nullable=False),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id")),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("hpp_per_kg", sa.Numeric(12, 2)),
        sa.Column("flag_hpp_belum_tersedia", sa.Boolean, server_default=sa.true()),
        sa.Column("tanggal_masuk", sa.Date, nullable=False),
        sa.Column("waktu_masuk", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "pk_tumpukan_to_silo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_pindah", sa.String(20), nullable=False, unique=True),
        sa.Column("pk_gudang2_intake_id", sa.Integer, sa.ForeignKey("pk_gudang2_intakes.id"), nullable=False),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pk_tumpukan_to_silo")
    op.drop_table("pk_gudang2_intakes")
    op.drop_table("pk_purchase_verifications")
    op.drop_table("pk_purchase_batches")
