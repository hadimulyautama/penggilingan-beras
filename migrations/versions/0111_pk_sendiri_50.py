"""PK giling sendiri: unit50kg dan sisa curah, tanpa backfill riwayat."""
from alembic import op
import sqlalchemy as sa
revision='0111_pk_sendiri_50'
down_revision='0110_portal_accounts'
branch_labels=depends_on=None


def upgrade():
    for table in ('internal_transfers','proyeksi_transfer_pk'):
        op.add_column(table,sa.Column('jumlah_karung',sa.Integer()))
        op.add_column(table,sa.Column('berat_curah_kg',sa.Numeric(12,2)))
        op.create_check_constraint('ck_'+table+'_karung50',table,
            '(jumlah_karung IS NULL AND berat_curah_kg IS NULL) OR '
            '(jumlah_karung IS NOT NULL AND berat_curah_kg IS NOT NULL AND jumlah_karung >= 0 '
            'AND berat_curah_kg >= 0 AND berat_curah_kg < 50 '
            'AND jumlah_karung * 50 + berat_curah_kg = berat_kg)')
    for table in ('pk_tumpukan_to_silo','proyeksi_pindah_tumpukan_silo'):
        op.add_column(table,sa.Column('jumlah_karung_50',sa.Integer()))
        op.add_column(table,sa.Column('berat_curah_kg',sa.Numeric(12,3)))
        op.create_check_constraint('ck_'+table+'_karung50',table,
            '(jumlah_karung_50 IS NULL AND berat_curah_kg IS NULL) OR '
            '(jumlah_karung_50 IS NOT NULL AND berat_curah_kg IS NOT NULL AND jumlah_karung IS NULL '
            'AND berat_kg IS NOT NULL AND jumlah_karung_50 >= 0 '
            'AND berat_curah_kg >= 0 AND berat_curah_kg < 50 '
            'AND jumlah_karung_50 * 50 + berat_curah_kg = berat_kg)')


def downgrade():
    b=op.get_bind()
    for table,col in [('internal_transfers','jumlah_karung'),('pk_tumpukan_to_silo','jumlah_karung_50')]:
        if b.scalar(sa.text('SELECT count(*) FROM '+table+' WHERE '+col+' IS NOT NULL')):
            raise RuntimeError('Unit PK50kg sudah dicatat; ekspor riwayat sebelum menurunkan versi.')
    for table,col in [('internal_transfers','jumlah_karung'),('proyeksi_transfer_pk','jumlah_karung'),('pk_tumpukan_to_silo','jumlah_karung_50'),('proyeksi_pindah_tumpukan_silo','jumlah_karung_50')]:
        op.drop_constraint('ck_'+table+'_karung50',table,type_='check')
        op.drop_column(table,'berat_curah_kg');op.drop_column(table,col)
