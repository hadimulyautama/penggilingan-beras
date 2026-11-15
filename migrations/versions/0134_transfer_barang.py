"""Transfer lokasi untuk persediaan umum; histori tidak ditulis ulang."""
from alembic import op
import sqlalchemy as sa
revision = '0134_transfer_barang'
down_revision = '0133_produk_perusahaan'
branch_labels = depends_on = None


def waktu():
    return [sa.Column(n,sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False) for n in ('created_at','updated_at')]


def upgrade():
    for table, col in [('permintaan_pk','tujuan_warehouse_id'),('internal_transfers','asal_warehouse_id'),('internal_transfers','tujuan_warehouse_id'),('packaging_purchases','warehouse_id'),('packaging_losses','warehouse_id'),('finished_goods_stock','warehouse_kemasan_id'),('gabah_kering_lots','warehouse_id'),('kemas_ulang','warehouse_id'),('kemas_ulang','warehouse_kemasan_asal_id'),('broken_karung_dibongkar','warehouse_kemasan_id')]:
        op.add_column(table,sa.Column(col,sa.Integer(),sa.ForeignKey('warehouses.id')))
    op.add_column('permintaan_pk',sa.Column('kunci_transfer',sa.String(120)))
    op.add_column('permintaan_pk',sa.Column('sidik_transfer',sa.String(64)))
    op.create_unique_constraint('uq_permintaan_pk_kunci_transfer','permintaan_pk',['kunci_transfer'])
    op.create_table('permintaan_transfer_barang',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('sumber_jenis',sa.String(24),nullable=False),sa.Column('sumber_id',sa.String(100),nullable=False),
        sa.Column('asal_id',sa.Integer(),sa.ForeignKey('warehouses.id'),nullable=False),sa.Column('tujuan_id',sa.Integer(),sa.ForeignKey('warehouses.id'),nullable=False),
        sa.Column('sumber',sa.JSON(),nullable=False),sa.Column('satuan',sa.String(12),nullable=False),
        sa.Column('jumlah_minta',sa.Numeric(14,2),nullable=False),sa.Column('jumlah_setuju',sa.Numeric(14,2),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('diminta_oleh',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('disetujui_oleh',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('waktu_minta',sa.DateTime(timezone=True),nullable=False),sa.Column('waktu_setuju',sa.DateTime(timezone=True)),
        sa.Column('ditutup',sa.Boolean(),nullable=False),sa.Column('alasan',sa.Text()),
        sa.Column('kunci',sa.String(120),unique=True,nullable=False),sa.Column('sidik',sa.String(64),nullable=False),*waktu(),
        sa.CheckConstraint("status IN ('diminta','disetujui','dikirim','selesai','ditolak','gugur')",name='ck_permintaan_transfer_barang_status'),
        sa.CheckConstraint('jumlah_minta > 0 AND jumlah_setuju >= 0',name='ck_permintaan_transfer_barang_jumlah'),
        sa.CheckConstraint('asal_id <> tujuan_id',name='ck_permintaan_transfer_barang_lokasi'))
    op.create_table('transfer_barang',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('pengiriman_pk_id',sa.Integer(),sa.ForeignKey('pengiriman_pk.id'),unique=True),
        sa.Column('asal_id',sa.Integer(),sa.ForeignKey('warehouses.id'),nullable=False),sa.Column('tujuan_id',sa.Integer(),sa.ForeignKey('warehouses.id'),nullable=False),
        sa.Column('dibuat_oleh',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('waktu',sa.DateTime(timezone=True),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('kunci',sa.String(120),unique=True,nullable=False),sa.Column('sidik',sa.String(64),nullable=False),*waktu(),
        sa.CheckConstraint("status IN ('selesai','dibatalkan')",name='ck_transfer_barang_status'))
    op.create_table('transfer_barang_items',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('transfer_id',sa.Integer(),sa.ForeignKey('transfer_barang.id'),nullable=False),sa.Column('permintaan_id',sa.Integer(),sa.ForeignKey('permintaan_transfer_barang.id'),nullable=False),
        sa.Column('jumlah',sa.Numeric(14,2),nullable=False),sa.Column('berat_kg',sa.Numeric(14,2)),sa.Column('dampak',sa.JSON(),nullable=False),
        sa.UniqueConstraint('transfer_id','permintaan_id',name='uq_transfer_barang_permintaan'),
        sa.CheckConstraint('jumlah >= 0 AND (berat_kg IS NULL OR berat_kg >= 0)',name='ck_transfer_barang_item_jumlah'))
    for table,cols in [('permintaan_transfer_barang',['asal_id','tujuan_id','status']),('transfer_barang',['asal_id','tujuan_id']),('transfer_barang_items',['transfer_id','permintaan_id'])]:
        for col in cols:op.create_index(f'ix_{table}_{col}',table,[col])
    op.create_index('ix_permintaan_transfer_barang_sumber','permintaan_transfer_barang',['sumber_jenis','sumber_id','status'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM permintaan_transfer_barang LIMIT 1')).first() or op.get_bind().execute(sa.text('SELECT 1 FROM permintaan_pk WHERE tujuan_warehouse_id IS NOT NULL LIMIT 1')).first():
        raise RuntimeError('Permintaan transfer barang sudah ada; rollback tidak boleh menghapus jejaknya.')
    for table in ['transfer_barang_items','transfer_barang','permintaan_transfer_barang']:op.drop_table(table)
    op.drop_constraint('uq_permintaan_pk_kunci_transfer','permintaan_pk',type_='unique')
    op.drop_column('permintaan_pk','kunci_transfer')
    op.drop_column('permintaan_pk','sidik_transfer')
    for table,col in [('permintaan_pk','tujuan_warehouse_id'),('internal_transfers','asal_warehouse_id'),('internal_transfers','tujuan_warehouse_id'),('packaging_purchases','warehouse_id'),('packaging_losses','warehouse_id'),('finished_goods_stock','warehouse_kemasan_id'),('gabah_kering_lots','warehouse_id'),('kemas_ulang','warehouse_id'),('kemas_ulang','warehouse_kemasan_asal_id'),('broken_karung_dibongkar','warehouse_kemasan_id')]:op.drop_column(table,col)
