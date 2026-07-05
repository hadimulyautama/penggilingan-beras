"""Inventory master: standar mutu, merk, kemasan, ukuran, SKU, beli/hilang karung

Revision ID: 0009_inventory_master
Revises: 0008_polishing
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_inventory_master"
down_revision: Union[str, None] = "0008_polishing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rice_quality_standards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(20), nullable=False, unique=True),
        sa.Column("nama", sa.String(50), nullable=False),
        sa.Column("urutan", sa.Integer, server_default="0"),
        sa.Column("aktif", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(50), nullable=False, unique=True),
        sa.Column("tipe", sa.String(10), server_default="house"),
        sa.Column("aktif", sa.Boolean, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "packaging_materials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(20), nullable=False, unique=True),
        sa.Column("nama", sa.String(50), nullable=False),
        sa.Column("aktif", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "package_sizes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ukuran_kg", sa.Integer, nullable=False, unique=True),
        sa.Column("aktif", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "product_skus",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kategori", sa.String(20), nullable=False),
        sa.Column("brand_id", sa.Integer, sa.ForeignKey("brands.id")),
        sa.Column("packaging_material_id", sa.Integer, sa.ForeignKey("packaging_materials.id"), nullable=False),
        sa.Column("package_size_id", sa.Integer, sa.ForeignKey("package_sizes.id"), nullable=False),
        sa.Column("aktif", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "packaging_purchases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(20), nullable=False, unique=True),
        sa.Column("packaging_material_id", sa.Integer, sa.ForeignKey("packaging_materials.id"), nullable=False),
        sa.Column("package_size_id", sa.Integer, sa.ForeignKey("package_sizes.id"), nullable=False),
        sa.Column("jumlah_lembar", sa.Integer, nullable=False),
        sa.Column("harga_per_lembar", sa.Numeric(12, 2)),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "packaging_losses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("packaging_material_id", sa.Integer, sa.ForeignKey("packaging_materials.id"), nullable=False),
        sa.Column("package_size_id", sa.Integer, sa.ForeignKey("package_sizes.id"), nullable=False),
        sa.Column("jumlah_lembar", sa.Integer, nullable=False),
        sa.Column("alasan", sa.String(120)),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("packaging_losses")
    op.drop_table("packaging_purchases")
    op.drop_table("product_skus")
    op.drop_table("package_sizes")
    op.drop_table("packaging_materials")
    op.drop_table("brands")
    op.drop_table("rice_quality_standards")
