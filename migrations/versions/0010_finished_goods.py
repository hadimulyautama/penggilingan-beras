"""Barang jadi: finished_goods_stock + byproduct_stock (bekatul) + byproduct_prices

Revision ID: 0010_finished_goods
Revises: 0009_inventory_master
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_finished_goods"
down_revision: Union[str, None] = "0009_inventory_master"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finished_goods_stock",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_sku_id", sa.Integer, sa.ForeignKey("product_skus.id"), nullable=False),
        sa.Column("rice_quality_standard_id", sa.Integer, sa.ForeignKey("rice_quality_standards.id")),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Integer),
        sa.Column("jumlah_karung", sa.Integer, nullable=False),
        sa.Column("berat_total_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("hpp_per_kg", sa.Numeric(12, 2)),
        sa.Column("warehouse_id", sa.Integer, sa.ForeignKey("warehouses.id")),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "byproduct_stock",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("jenis_produk", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Integer),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="tersedia"),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "byproduct_prices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("jenis", sa.String(20), nullable=False),
        sa.Column("harga_per_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("byproduct_prices")
    op.drop_table("byproduct_stock")
    op.drop_table("finished_goods_stock")
