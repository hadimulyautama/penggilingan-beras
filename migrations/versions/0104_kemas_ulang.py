"""Kemas ulang dan stok sisa curah tanpa mengembalikan karung lama."""
from alembic import op
import sqlalchemy as sa
revision='0104_kemas_ulang'
down_revision='0103_draf_dihapus'
branch_labels=depends_on=None

def upgrade():
    op.add_column('finished_goods_stock',sa.Column('curah_kemas_ulang',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_table('kemas_ulang',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('kunci',sa.String(64),nullable=False,unique=True),
        sa.Column('sidik',sa.String(64),nullable=False),
        sa.Column('sumber_id',sa.Integer(),sa.ForeignKey('finished_goods_stock.id'),nullable=False),
        sa.Column('sku_asal_id',sa.Integer(),sa.ForeignKey('product_skus.id'),nullable=False),
        sa.Column('sku_baru_id',sa.Integer(),sa.ForeignKey('product_skus.id'),nullable=False),
        sa.Column('jasa_id',sa.Integer(),sa.ForeignKey('jasa.id')),
        sa.Column('karung_dibuka',sa.Integer(),nullable=False),
        sa.Column('karung_lama_dihitung',sa.Integer(),nullable=False),
        sa.Column('berat_asal_kg',sa.Numeric(12,2),nullable=False),
        sa.Column('karung_baru',sa.Integer(),nullable=False),
        sa.Column('berat_baru_kg',sa.Numeric(12,2),nullable=False),
        sa.Column('sisa_kg',sa.Numeric(12,2),nullable=False),
        sa.Column('petugas_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('waktu',sa.DateTime(timezone=True),nullable=False))

def downgrade():
    op.drop_table('kemas_ulang')
    op.drop_column('finished_goods_stock','curah_kemas_ulang')
