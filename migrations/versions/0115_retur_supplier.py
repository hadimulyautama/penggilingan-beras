"""Pengajuan Retur ke Supplier; tidak mengubah sumber atau saldo historis."""
from alembic import op
import sqlalchemy as sa

revision = "0115_retur_supplier"
down_revision = "0114_kiriman_pelanggan"
branch_labels = depends_on = None

def upgrade():
    op.create_table('retur_supplier',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('kode', sa.String(length=32), unique=True, nullable=False),
        sa.Column('penerimaan_tiket_id', sa.Integer(), nullable=False),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id'), nullable=False),
        sa.Column('timbangan_transaksi_id', sa.Integer(), unique=True, nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('alasan', sa.Text(), nullable=False),
        sa.Column('catatan', sa.Text(), nullable=True),
        sa.Column('sumber', sa.JSON(), nullable=False),
        sa.Column('kunci', sa.String(length=64), unique=True, nullable=False),
        sa.Column('sidik', sa.String(length=64), nullable=False),
        sa.Column('input_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('waktu', sa.DateTime(timezone=True), nullable=False),
        sa.Column('tiket_dihubungkan_oleh', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('tiket_dihubungkan_pada', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dibatalkan_oleh', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('dibatalkan_pada', sa.DateTime(timezone=True), nullable=True),
        sa.Column('alasan_batal', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('diajukan','dibatalkan')", name='ck_retur_supplier_status'))
    op.create_index('ix_retur_supplier_penerimaan', 'retur_supplier', ['penerimaan_tiket_id'], unique=False)
    op.create_table('retur_supplier_items',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('retur_supplier_id', sa.Integer(), sa.ForeignKey('retur_supplier.id'), nullable=False),
        sa.Column('kunci_sumber', sa.String(length=64), nullable=False),
        sa.Column('purchase_batch_id', sa.Integer(), sa.ForeignKey('purchase_batches.id'), nullable=True),
        sa.Column('pk_purchase_batch_id', sa.Integer(), sa.ForeignKey('pk_purchase_batches.id'), nullable=True),
        sa.Column('finished_goods_stock_id', sa.Integer(), sa.ForeignKey('finished_goods_stock.id'), nullable=True),
        sa.Column('byproduct_stock_id', sa.Integer(), sa.ForeignKey('byproduct_stock.id'), nullable=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('jumlah', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('satuan', sa.String(length=12), nullable=False),
        sa.Column('bobot_kg', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('tipe_pool', sa.String(length=24), nullable=False),
        sa.Column('product_sku_id', sa.Integer(), sa.ForeignKey('product_skus.id'), nullable=True),
        sa.Column('rice_quality_standard_id', sa.Integer(), sa.ForeignKey('rice_quality_standards.id'), nullable=True),
        sa.Column('jenis_produk', sa.String(length=24), nullable=True),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.CheckConstraint('jumlah > 0 AND bobot_kg > 0', name='ck_retur_supplier_item_positif'),
        sa.CheckConstraint("satuan IN ('karung','kg') AND (satuan <> 'karung' OR jumlah = round(jumlah))", name='ck_retur_supplier_item_satuan'),
        sa.CheckConstraint('(CASE WHEN purchase_batch_id IS NULL THEN 0 ELSE 1 END + CASE WHEN pk_purchase_batch_id IS NULL THEN 0 ELSE 1 END + CASE WHEN finished_goods_stock_id IS NULL THEN 0 ELSE 1 END + CASE WHEN byproduct_stock_id IS NULL THEN 0 ELSE 1 END) = 1', name='ck_retur_supplier_satu_sumber'),
        sa.UniqueConstraint('retur_supplier_id','kunci_sumber', name='uq_retur_supplier_item_sumber'))
    op.create_index('ix_retur_supplier_item_sumber', 'retur_supplier_items', ['kunci_sumber'], unique=False)

def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM retur_supplier")):
        raise RuntimeError("Pengajuan telah digunakan; pertahankan sumber dan auditnya.")
    op.drop_index('ix_retur_supplier_item_sumber',table_name='retur_supplier_items')
    op.drop_table('retur_supplier_items')
    op.drop_index('ix_retur_supplier_penerimaan',table_name='retur_supplier')
    op.drop_table('retur_supplier')
