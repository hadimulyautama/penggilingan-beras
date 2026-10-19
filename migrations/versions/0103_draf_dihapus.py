"""Draf dihapus secara lunak, tanpa menghapus perintah atau audit."""
from alembic import op
import sqlalchemy as sa
revision='0103_draf_dihapus'
down_revision='0102_draf_keluar'
branch_labels=depends_on=None

def upgrade():
    op.add_column('draf_keluar',sa.Column('dihapus_pada',sa.DateTime(timezone=True)))

def downgrade():
    op.drop_column('draf_keluar','dihapus_pada')
