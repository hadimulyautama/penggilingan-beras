"""Transfer PK tanpa kendaraan, tanpa identitas kendaraan atau tiket fiktif."""
from alembic import op
import sqlalchemy as sa
revision='0127_transfer_tanpa_kendaraan'
down_revision='0126_pengiriman_pk'
branch_labels=depends_on=None

def upgrade():
    op.add_column('pengiriman_pk',sa.Column('pakai_kendaraan',sa.Boolean(),server_default=sa.true(),nullable=False))
    op.alter_column('pengiriman_pk','nomor_polisi',existing_type=sa.String(30),nullable=True)
    op.alter_column('pengiriman_pk','nama_sopir',existing_type=sa.String(100),nullable=True)
    op.create_check_constraint('ck_pengiriman_pk_kendaraan','pengiriman_pk',"(pakai_kendaraan AND nomor_polisi IS NOT NULL AND nama_sopir IS NOT NULL) OR (NOT pakai_kendaraan AND nomor_polisi IS NULL AND nama_sopir IS NULL AND tiket_id IS NULL AND status = 'selesai')")

def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM pengiriman_pk WHERE NOT pakai_kendaraan LIMIT 1')).first():
        raise RuntimeError('Transfer tanpa kendaraan sudah tercatat; rollback tidak boleh menghapus jejaknya.')
    op.drop_constraint('ck_pengiriman_pk_kendaraan','pengiriman_pk',type_='check')
    op.alter_column('pengiriman_pk','nomor_polisi',existing_type=sa.String(30),nullable=False)
    op.alter_column('pengiriman_pk','nama_sopir',existing_type=sa.String(100),nullable=False)
    op.drop_column('pengiriman_pk','pakai_kendaraan')
