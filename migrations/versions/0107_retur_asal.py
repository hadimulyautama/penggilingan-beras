"""Asal pengiriman, pemeriksaan bertahap, dan audit koreksi retur.

Tidak melakukan backfill hubungan asal pada histori tanpa bukti.
"""
from alembic import op
import sqlalchemy as sa

revision = '0107_retur_asal'
down_revision = '0106_kabar_pribadi'
branch_labels = depends_on = None


def upgrade():
    op.alter_column('customer_return_items', 'product_sku_id', nullable=True)
    op.add_column('retur_rincian', sa.Column('outgoing_record_id', sa.Integer(), sa.ForeignKey('outgoing_records.id')))
    op.create_index('ix_retur_rincian_outgoing_record_id', 'retur_rincian', ['outgoing_record_id'])
    op.add_column('retur_rincian', sa.Column('status_pemeriksaan', sa.String(32)))
    op.add_column('retur_rincian', sa.Column('wajib_manual', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('retur_rincian', sa.Column('hasil_pemeriksaan', sa.JSON()))
    op.add_column('retur_rincian', sa.Column('customer_return_id', sa.Integer(), sa.ForeignKey('customer_returns.id')))
    op.create_unique_constraint('uq_retur_rincian_customer_return_id', 'retur_rincian', ['customer_return_id'])
    op.add_column('retur_rincian', sa.Column('catatan', sa.String(500)))
    op.add_column('customer_return_items', sa.Column('outgoing_item_id', sa.Integer(), sa.ForeignKey('outgoing_items.id')))
    op.create_index('ix_customer_return_items_outgoing_item_id', 'customer_return_items', ['outgoing_item_id'])
    op.create_table('retur_pemeriksaan_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('retur_rincian_id', sa.Integer(), sa.ForeignKey('retur_rincian.id'), nullable=False),
        sa.Column('pelaku_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('waktu', sa.DateTime(timezone=True), nullable=False),
        sa.Column('aksi', sa.String(32), nullable=False),
        sa.Column('alasan', sa.String(500)),
        sa.Column('sebelum', sa.JSON()),
        sa.Column('sesudah', sa.JSON(), nullable=False))
    op.create_index('ix_retur_pemeriksaan_log_retur_rincian_id', 'retur_pemeriksaan_log', ['retur_rincian_id'])


def downgrade():
    # Histori curah tidak dapat dipaksa menjadi SKU kemasan. Downgrade hanya
    # sah bila belum ada penerimaan jenis tersebut.
    op.alter_column('customer_return_items', 'product_sku_id', nullable=False)
    op.drop_table('retur_pemeriksaan_log')
    op.drop_index('ix_customer_return_items_outgoing_item_id', 'customer_return_items')
    op.drop_column('customer_return_items', 'outgoing_item_id')
    op.drop_column('retur_rincian', 'catatan')
    op.drop_constraint('uq_retur_rincian_customer_return_id', 'retur_rincian', type_='unique')
    op.drop_column('retur_rincian', 'customer_return_id')
    op.drop_column('retur_rincian', 'hasil_pemeriksaan')
    op.drop_column('retur_rincian', 'wajib_manual')
    op.drop_column('retur_rincian', 'status_pemeriksaan')
    op.drop_index('ix_retur_rincian_outgoing_record_id', 'retur_rincian')
    op.drop_column('retur_rincian', 'outgoing_record_id')
