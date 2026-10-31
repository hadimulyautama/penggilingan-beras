"""Koreksi pengiriman terverifikasi; tidak mengubah baris/data historis saat migrasi."""
from alembic import op
import sqlalchemy as sa
revision = '0118_koreksi_pengiriman'
down_revision = '0117_retur_supplier_koreksi'
branch_labels = depends_on = None


def upgrade():
    op.create_table('koreksi_pengiriman',
        sa.Column('kunci', sa.String(64), primary_key=True),
        sa.Column('outgoing_record_id', sa.Integer(), sa.ForeignKey('outgoing_records.id'), nullable=False),
        sa.Column('versi', sa.Integer(), nullable=False),
        sa.Column('sidik_input', sa.String(64), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('input_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('waktu', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('outgoing_record_id','versi',name='uq_koreksi_pengiriman_versi'))
    op.create_index('ix_koreksi_pengiriman_outgoing_record_id','koreksi_pengiriman',['outgoing_record_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM koreksi_pengiriman')):
        raise RuntimeError('Audit koreksi tidak boleh dihapus melalui downgrade.')
    op.drop_table('koreksi_pengiriman')
