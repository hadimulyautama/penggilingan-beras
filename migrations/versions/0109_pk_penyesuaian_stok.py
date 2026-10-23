"""Penyesuaian stok PK lama yang bertanggal, tanpa backfill atau ubah laporan."""
from alembic import op
import sqlalchemy as sa

revision = '0109_pk_penyesuaian_stok'
down_revision = '0108_pk_karung'
branch_labels = depends_on = None


def upgrade():
    op.create_table('pk_penyesuaian_stok',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('intake_id', sa.Integer(), sa.ForeignKey('pk_gudang2_intakes.id'), nullable=False),
        sa.Column('selisih_kg', sa.Numeric(12, 3), nullable=False),
        sa.Column('tanggal', sa.Date(), nullable=False),
        sa.Column('waktu', sa.DateTime(timezone=True), nullable=False),
        sa.Column('alasan', sa.String(500), nullable=False),
        sa.Column('input_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM pk_penyesuaian_stok')):
        raise RuntimeError('Penyesuaian stok sudah tercatat; ekspor riwayat sebelum menurunkan versi.')
    op.drop_table('pk_penyesuaian_stok')
