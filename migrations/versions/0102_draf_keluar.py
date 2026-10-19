"""Draf perintah pribadi, terpisah dari antrean dan stok."""
from alembic import op
import sqlalchemy as sa
revision = '0102_draf_keluar'
down_revision = '0101_jeda_kejadian'
branch_labels = depends_on = None

def upgrade():
    op.create_table('draf_keluar',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('pemilik_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('isi', sa.JSON(), nullable=False),
        sa.Column('revisi', sa.Integer(), nullable=False),
        sa.Column('kiriman', sa.String(36)), sa.Column('sidik', sa.String(64)),
        sa.Column('perintah_id', sa.Integer(), sa.ForeignKey('outgoing_records.id'), unique=True),
        sa.Column('diperbarui', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_draf_keluar_pemilik_id','draf_keluar',['pemilik_id'])

def downgrade():
    op.drop_table('draf_keluar')
