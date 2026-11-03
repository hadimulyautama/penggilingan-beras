"""Alokasi efektif bahan silo; penerimaan dan timbang asal tetap utuh."""
from alembic import op
import sqlalchemy as sa
revision = '0119_koreksi_bahan_berjalan'
down_revision = '0118_koreksi_pengiriman'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('silo_storage', sa.Column('alokasi_koreksi_kg', sa.Numeric(12,3), nullable=True))
    op.create_check_constraint('ck_silo_alokasi_koreksi_nonnegatif','silo_storage',
                               'alokasi_koreksi_kg IS NULL OR alokasi_koreksi_kg >= 0')

def downgrade():
    op.drop_constraint('ck_silo_alokasi_koreksi_nonnegatif','silo_storage',type_='check')
    op.drop_column('silo_storage','alokasi_koreksi_kg')
