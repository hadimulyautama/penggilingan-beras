"""Catat penerimaan retur pelanggan dan rincian stoknya."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0095_customer_returns"
down_revision: Union[str, None] = "0094_kemasan_pabrik_beras_timbang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode", sa.String(24), nullable=False, unique=True),
        sa.Column("timbangan_transaksi_id", sa.Integer(), nullable=False),
        sa.Column("kode_tiket", sa.String(32), nullable=False),
        sa.Column("pelanggan_id", sa.Integer(), sa.ForeignKey("pelanggan.id")),
        sa.Column("nama_pelanggan", sa.String(150)),
        sa.Column("nomor_polisi", sa.String(20)),
        sa.Column("timbang1_kg", sa.Numeric(12, 2)),
        sa.Column("timbang2_kg", sa.Numeric(12, 2)),
        sa.Column("berat_tiket_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("berat_rincian_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("selisih_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("alasan_selisih", sa.String(300)),
        sa.Column("catatan", sa.String(500)),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id")),
        sa.Column("input_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("uq_customer_returns_timbangan", "customer_returns",
                    ["timbangan_transaksi_id"], unique=True)
    op.create_table(
        "customer_return_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_return_id", sa.Integer(),
                  sa.ForeignKey("customer_returns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_sku_id", sa.Integer(), sa.ForeignKey("product_skus.id"), nullable=False),
        sa.Column("rice_quality_standard_id", sa.Integer(),
                  sa.ForeignKey("rice_quality_standards.id")),
        sa.Column("jumlah_karung", sa.Integer(), nullable=False),
        sa.Column("berat_total_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("jasa_id", sa.Integer(), sa.ForeignKey("jasa.id")),
        sa.Column("catatan", sa.String(200)),
        sa.Column("finished_goods_stock_id", sa.Integer(),
                  sa.ForeignKey("finished_goods_stock.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_customer_return_items_return", "customer_return_items",
                    ["customer_return_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_return_items_return", table_name="customer_return_items")
    op.drop_table("customer_return_items")
    op.drop_index("uq_customer_returns_timbangan", table_name="customer_returns")
    op.drop_table("customer_returns")
