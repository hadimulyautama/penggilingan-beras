"""Pemeriksaan dan proyeksi keluar supplier; penerimaan lama tetap utuh."""
from alembic import op
import sqlalchemy as sa
revision='0116_retur_supplier_keluar'
down_revision='0115_retur_supplier'
branch_labels=depends_on=None


def upgrade():
    # Rasio karung PK layanan lama tidak dibulatkan menjadi kg dua desimal
    # setiap kali dipakai. Pertahankan presisinya pada suku keluar supplier.
    op.alter_column('retur_supplier_items','bobot_kg',existing_type=sa.Numeric(14,2),type_=sa.Numeric(22,8),existing_nullable=False)
    for nama,kolom in [('gabah','purchase_batch_id'),('pk','pk_purchase_batch_id'),('beras','finished_goods_stock_id'),('broken','byproduct_stock_id')]:
        op.create_index('ix_retur_supplier_item_'+nama,'retur_supplier_items',[kolom])
    op.drop_constraint('ck_retur_supplier_status','retur_supplier',type_='check')
    op.create_check_constraint('ck_retur_supplier_status','retur_supplier',"status IN ('diajukan','dibatalkan','selesai_gudang')")
    op.add_column('retur_supplier',sa.Column('versi_aktual',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('retur_supplier',sa.Column('wajib_manual',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('retur_supplier',sa.Column('dasar_selisih_besar',sa.JSON()))
    op.add_column('retur_supplier',sa.Column('verifikasi',sa.JSON()))
    op.create_table('retur_supplier_aktual',
        sa.Column('item_id',sa.Integer(),sa.ForeignKey('retur_supplier_items.id'),primary_key=True),
        sa.Column('jumlah',sa.Numeric(14,2),nullable=False),sa.Column('bobot_kg',sa.Numeric(22,8),nullable=False),
        sa.Column('kemasan_tara_id',sa.Integer(),sa.ForeignKey('kemasan_tara.id')),
        sa.Column('tara_per_karung_kg',sa.Numeric(10,4)),
        sa.CheckConstraint('jumlah >= 0 AND bobot_kg >= 0',name='ck_rsp_aktual_positif'))
    op.create_table('retur_supplier_pemeriksaan',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('retur_supplier_id',sa.Integer(),sa.ForeignKey('retur_supplier.id'),nullable=False),
        sa.Column('versi_aktual',sa.Integer(),nullable=False),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('input_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('waktu',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_retur_supplier_pemeriksaan_retur_supplier_id','retur_supplier_pemeriksaan',['retur_supplier_id'])
    op.create_table('retur_supplier_keluar',
        sa.Column('peristiwa_id',sa.BigInteger().with_variant(sa.Integer(),'sqlite'),sa.ForeignKey('peristiwa.id'),primary_key=True),
        sa.Column('retur_supplier_id',sa.Integer(),sa.ForeignKey('retur_supplier.id'),unique=True,nullable=False),
        sa.Column('kode',sa.String(32),unique=True,nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('input_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('waktu',sa.DateTime(timezone=True),nullable=False))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM retur_supplier')):
        raise RuntimeError('Riwayat pemeriksaan/keluar tidak boleh dihapus melalui downgrade.')
    op.drop_table('retur_supplier_keluar');op.drop_table('retur_supplier_pemeriksaan');op.drop_table('retur_supplier_aktual')
    op.alter_column('retur_supplier_items','bobot_kg',existing_type=sa.Numeric(22,8),type_=sa.Numeric(14,2),existing_nullable=False)
    for nama in ['gabah','pk','beras','broken']:op.drop_index('ix_retur_supplier_item_'+nama,table_name='retur_supplier_items')
    for c in ['verifikasi','dasar_selisih_besar','wajib_manual','versi_aktual']:op.drop_column('retur_supplier',c)
    op.drop_constraint('ck_retur_supplier_status','retur_supplier',type_='check')
    op.create_check_constraint('ck_retur_supplier_status','retur_supplier',"status IN ('diajukan','dibatalkan')")
