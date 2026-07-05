"""Barang keluar / dikirim: outgoing_records + outgoing_items

Revision ID: 0011_outgoing
Revises: 0010_finished_goods
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_outgoing"
down_revision: Union[str, None] = "0010_finished_goods"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outgoing_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(20), nullable=False, unique=True),
        sa.Column("warehouse_id", sa.Integer, sa.ForeignKey("warehouses.id")),
        sa.Column("nama_pembeli", sa.String(100)),
        sa.Column("metode", sa.String(20)),
        sa.Column("no_polisi", sa.String(20)),
        sa.Column("nama_ekspedisi", sa.String(100)),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("catatan", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "outgoing_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("outgoing_record_id", sa.Integer, sa.ForeignKey("outgoing_records.id"), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("product_sku_id", sa.Integer, sa.ForeignKey("product_skus.id")),
        sa.Column("rice_quality_standard_id", sa.Integer, sa.ForeignKey("rice_quality_standards.id")),
        sa.Column("jenis_byproduct", sa.String(20)),
        sa.Column("milling_process_id", sa.Integer, sa.ForeignKey("milling_process.id")),
        sa.Column("jumlah_karung", sa.Integer),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("harga_per_kg", sa.Numeric(12, 2)),
        sa.Column("total_harga", sa.Numeric(16, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("outgoing_items")
    op.drop_table("outgoing_records")
