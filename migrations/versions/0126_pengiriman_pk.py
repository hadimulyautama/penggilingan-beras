"""Perjalanan PK bertahap, tanpa menulis ulang transfer historis."""
from alembic import op
import sqlalchemy as sa
revision='0126_pengiriman_pk'
down_revision='0125_samping_sumber'
branch_labels=depends_on=None

def upgrade():
    op.add_column('permintaan_pk',sa.Column('bertahap',sa.Boolean(),server_default=sa.false(),nullable=False))
    op.create_table('pengiriman_pk',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('status',sa.String(24),nullable=False),
        sa.Column('kunci',sa.String(120),nullable=False,unique=True),sa.Column('sidik',sa.String(64),nullable=False),
        sa.Column('asal_id',sa.Integer(),sa.ForeignKey('warehouses.id'),nullable=False),sa.Column('tujuan_id',sa.Integer(),sa.ForeignKey('warehouses.id'),nullable=False),
        sa.Column('silo_id',sa.Integer(),sa.ForeignKey('silos.id')),sa.Column('jasa_id',sa.Integer(),sa.ForeignKey('jasa.id')),
        sa.Column('nomor_polisi',sa.String(30),nullable=False),sa.Column('nama_sopir',sa.String(100),nullable=False),
        sa.Column('dibuat_oleh',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('waktu',sa.DateTime(timezone=True),nullable=False),
        sa.Column('tiket_id',sa.Integer(),unique=True),sa.Column('bobot_timbang_kg',sa.Numeric(14,4)),sa.Column('selisih_kg',sa.Numeric(14,4)),
        sa.Column('alasan',sa.Text()),sa.Column('diputus_oleh',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('waktu_selesai',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("status IN ('dalam_perjalanan','menunggu_admin','selesai','dibatalkan')",name='ck_pengiriman_pk_status'))
    op.create_table('pengiriman_pk_items',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('pengiriman_id',sa.Integer(),sa.ForeignKey('pengiriman_pk.id'),nullable=False),
        sa.Column('permintaan_id',sa.Integer(),sa.ForeignKey('permintaan_pk.id'),nullable=False),sa.Column('berat_kg',sa.Numeric(12,2),nullable=False),
        sa.Column('internal_transfer_id',sa.Integer(),sa.ForeignKey('internal_transfers.id'),unique=True),
        sa.UniqueConstraint('pengiriman_id','permintaan_id',name='uq_pengiriman_pk_permintaan'),sa.CheckConstraint('berat_kg > 0',name='ck_pengiriman_pk_item_positif'))
    op.create_index('ix_pengiriman_pk_items_pengiriman_id','pengiriman_pk_items',['pengiriman_id'])
    op.create_index('ix_pengiriman_pk_items_permintaan_id','pengiriman_pk_items',['permintaan_id'])

def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM pengiriman_pk LIMIT 1')).first():
        raise RuntimeError('Perjalanan PK sudah tercatat; rollback tidak boleh menghapus jejaknya.')
    op.drop_table('pengiriman_pk_items');op.drop_table('pengiriman_pk');op.drop_column('permintaan_pk','bertahap')
