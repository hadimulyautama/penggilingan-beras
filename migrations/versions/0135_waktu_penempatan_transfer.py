"""Pisahkan waktu penempatan gudang dari waktu penerimaan/pengemasan asal."""
from alembic import op
import sqlalchemy as sa

revision='0135_waktu_penempatan_transfer'
down_revision='0134_transfer_barang'
branch_labels=depends_on=None


def upgrade():
    for table in ('finished_goods_stock','byproduct_stock','pk_gudang2_intakes'):
        op.add_column(table,sa.Column('waktu_penempatan',sa.DateTime(timezone=True)))


def downgrade():
    for table in ('finished_goods_stock','byproduct_stock','pk_gudang2_intakes'):
        if op.get_bind().execute(sa.text(f'SELECT 1 FROM {table} WHERE waktu_penempatan IS NOT NULL LIMIT 1')).first():
            raise RuntimeError('Penempatan transfer sudah tercatat; waktu asal tidak boleh menggantikan urutan kedatangan gudang.')
    for table in ('finished_goods_stock','byproduct_stock','pk_gudang2_intakes'):
        op.drop_column(table,'waktu_penempatan')
