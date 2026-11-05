"""Identitas gudang penerimaan baru; tanpa backfill atau mutasi historis."""
from alembic import op
import sqlalchemy as sa
revision='0123_lokasi_penerimaan'
down_revision='0122_fasilitas'
branch_labels=depends_on=None

def upgrade():
    for table in ('purchase_batches','pk_purchase_batches','byproduct_stock'):
        op.add_column(table,sa.Column('warehouse_id',sa.Integer(),sa.ForeignKey('warehouses.id')))
        op.create_index('ix_'+table+'_warehouse_id',table,['warehouse_id'])

def downgrade():
    for table in ('purchase_batches','pk_purchase_batches','byproduct_stock'):
        op.drop_index('ix_'+table+'_warehouse_id',table_name=table)
        op.drop_column(table,'warehouse_id')
