"""Sumber hasil samping beli luar, tanpa mengubah transaksi historis."""
from alembic import op
import sqlalchemy as sa
revision='0125_samping_sumber'
down_revision='0124_master_hasil'
branch_labels=depends_on=None

def upgrade():
    op.add_column('hasil_samping_ke_silo',sa.Column('byproduct_stock_id',sa.Integer(),sa.ForeignKey('byproduct_stock.id'),nullable=True))
    op.alter_column('hasil_samping_ke_silo','polishing_process_id',existing_type=sa.Integer(),nullable=True)
    op.create_check_constraint('ck_hss_satu_sumber','hasil_samping_ke_silo','(polishing_process_id IS NULL) <> (byproduct_stock_id IS NULL)')
    op.create_index('ix_hss_stok_sumber','hasil_samping_ke_silo',['byproduct_stock_id'])

def downgrade():
    # Tolak rollback skema bila sudah ada transaksi sumber baru, jangan hapus datanya.
    if op.get_bind().execute(sa.text('SELECT 1 FROM hasil_samping_ke_silo WHERE polishing_process_id IS NULL LIMIT 1')).first():
        raise RuntimeError('Transaksi sumber hasil samping baru masih ada; gunakan rollback kode yang kompatibel.')
    op.drop_index('ix_hss_stok_sumber',table_name='hasil_samping_ke_silo')
    op.drop_constraint('ck_hss_satu_sumber','hasil_samping_ke_silo',type_='check')
    op.drop_column('hasil_samping_ke_silo','byproduct_stock_id')
    op.alter_column('hasil_samping_ke_silo','polishing_process_id',existing_type=sa.Integer(),nullable=False)
