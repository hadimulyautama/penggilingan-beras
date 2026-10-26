"""Pertahankan karung terpakai saat isi broken dibongkar; tanpa backfill tebakan."""
from alembic import op
import sqlalchemy as sa
revision='0113_broken_karung_dibongkar'
down_revision='0112_akun_perangkat_pribadi'
branch_labels=depends_on=None


def upgrade():
    op.create_table('broken_karung_dibongkar',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('polishing_process_id',sa.Integer(),sa.ForeignKey('polishing_process.id'),nullable=False),
        sa.Column('stok_asal_id',sa.Integer(),nullable=False),
        sa.Column('product_sku_id',sa.Integer(),sa.ForeignKey('product_skus.id'),nullable=False),
        sa.Column('jumlah_karung',sa.Integer(),nullable=False),
        sa.Column('berat_kg',sa.Numeric(12,2),nullable=False),
        sa.Column('jasa_id',sa.Integer(),sa.ForeignKey('jasa.id')),
        sa.Column('mengurangi_stok',sa.Boolean(),nullable=False),
        sa.Column('waktu',sa.DateTime(timezone=True),nullable=False),
        sa.Column('input_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=False))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM broken_karung_dibongkar')):
        raise RuntimeError('Jejak pembongkaran sudah tersimpan; pertahankan riwayat sebelum menurunkan versi.')
    op.drop_table('broken_karung_dibongkar')
