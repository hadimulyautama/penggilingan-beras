"""Selisih koreksi dan pembatalan administratif; tidak mengubah transaksi lama."""
from alembic import op
import sqlalchemy as sa
revision='0117_retur_supplier_koreksi'
down_revision='0116_retur_supplier_keluar'
branch_labels=depends_on=None


def upgrade():
    op.create_table('retur_supplier_efektif',sa.Column('retur_supplier_id',sa.Integer(),sa.ForeignKey('retur_supplier.id'),primary_key=True),
        sa.Column('versi',sa.Integer(),nullable=False),sa.Column('keterangan',sa.Text()),sa.Column('dibatalkan',sa.Boolean(),nullable=False),
        sa.Column('keberadaan',sa.String(20)),sa.Column('wajib_manual',sa.Boolean(),nullable=False),sa.Column('dasar_besar',sa.JSON()))
    op.create_table('retur_supplier_perubahan',sa.Column('peristiwa_id',sa.BigInteger().with_variant(sa.Integer(),'sqlite'),sa.ForeignKey('peristiwa.id'),primary_key=True),
        sa.Column('retur_supplier_id',sa.Integer(),sa.ForeignKey('retur_supplier.id'),nullable=False),sa.Column('versi',sa.Integer(),nullable=False),
        sa.Column('jenis',sa.String(20),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('input_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('waktu',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('retur_supplier_id','versi',name='uq_rsp_perubahan_versi'))
    op.create_index('ix_retur_supplier_perubahan_retur_supplier_id','retur_supplier_perubahan',['retur_supplier_id'])
    op.create_table('retur_supplier_selisih',sa.Column('peristiwa_id',sa.BigInteger().with_variant(sa.Integer(),'sqlite'),sa.ForeignKey('retur_supplier_perubahan.peristiwa_id'),primary_key=True),
        sa.Column('item_id',sa.Integer(),sa.ForeignKey('retur_supplier_items.id'),primary_key=True),sa.Column('bobot_kg',sa.Numeric(22,8),nullable=False),sa.Column('jumlah',sa.Numeric(14,2),nullable=False))
    op.create_index('ix_retur_supplier_selisih_item_id','retur_supplier_selisih',['item_id'])
    op.create_table('retur_supplier_draf_koreksi',sa.Column('kunci',sa.String(64),primary_key=True),sa.Column('retur_supplier_id',sa.Integer(),sa.ForeignKey('retur_supplier.id'),nullable=False),
        sa.Column('versi',sa.Integer(),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('input_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('waktu',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_retur_supplier_draf_koreksi_retur_supplier_id','retur_supplier_draf_koreksi',['retur_supplier_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM retur_supplier_perubahan')) or op.get_bind().scalar(sa.text('SELECT count(*) FROM retur_supplier_draf_koreksi')):
        raise RuntimeError('Jejak koreksi dan pemeriksaan tidak boleh dihapus melalui downgrade.')
    for t in ('retur_supplier_draf_koreksi','retur_supplier_selisih','retur_supplier_perubahan','retur_supplier_efektif'):op.drop_table(t)
