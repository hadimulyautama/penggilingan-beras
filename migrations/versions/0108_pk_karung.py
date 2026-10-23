"""PK beli luar: jumlah karung tetap, bobot turun dari partai tanpa backfill."""
from alembic import op
import sqlalchemy as sa

revision = '0108_pk_karung'
down_revision = '0107_retur_asal'
branch_labels = depends_on = None


def upgrade():
    op.add_column('pk_purchase_batches', sa.Column('jumlah_karung', sa.Integer()))
    op.add_column('pk_purchase_batches', sa.Column('ukuran_karung_kg', sa.Numeric(12, 2)))
    for tabel in ('pk_tumpukan_to_silo', 'proyeksi_pindah_tumpukan_silo'):
        op.add_column(tabel, sa.Column('jumlah_karung', sa.Integer()))
        op.alter_column(tabel, 'berat_kg', type_=sa.Numeric(12, 3), nullable=True)
        op.create_check_constraint('ck_' + tabel + '_satuan', tabel,
            '(jumlah_karung IS NULL AND berat_kg IS NOT NULL) OR '
            '(jumlah_karung > 0 AND berat_kg IS NULL)')
    op.add_column('pk_tumpukan_to_silo', sa.Column('pemakaian_silo_id', sa.Integer(),
        sa.ForeignKey('polishing_silo_usage.id', name='fk_pindah_pk_pemakaian')))
    op.add_column('pk_tumpukan_to_silo', sa.Column('selama_proses', sa.Boolean(),
        nullable=False, server_default=sa.text('false')))
    op.add_column('polishing_silo_usage', sa.Column('bobot_karung_dinamis', sa.Boolean(),
        nullable=False, server_default=sa.text('false')))
    for kolom in ('berat_awal_kg', 'berat_masuk_kg', 'berat_terpakai_kg'):
        op.alter_column('polishing_silo_usage', kolom, type_=sa.Numeric(12, 3))


def downgrade():
    # Menurunkan versi tidak boleh membuang jumlah karung yang sudah menjadi
    # bukti pemindahan, atau mengarang kg penggantinya dari bobot terkini.
    sambungan = op.get_bind()
    ada = sambungan.scalar(sa.text('SELECT count(*) FROM pk_tumpukan_to_silo WHERE jumlah_karung IS NOT NULL'))
    if ada:
        raise RuntimeError('Pemindahan berkarung sudah tercatat; ekspor riwayat sebelum menurunkan versi.')
    op.drop_column('polishing_silo_usage', 'bobot_karung_dinamis')
    op.drop_column('pk_tumpukan_to_silo', 'selama_proses')
    op.drop_column('pk_tumpukan_to_silo', 'pemakaian_silo_id')
    for tabel in ('pk_tumpukan_to_silo', 'proyeksi_pindah_tumpukan_silo'):
        op.drop_constraint('ck_' + tabel + '_satuan', tabel, type_='check')
        op.drop_column(tabel, 'jumlah_karung')
        op.alter_column(tabel, 'berat_kg', type_=sa.Numeric(12, 2), nullable=False)
    for kolom in ('berat_awal_kg', 'berat_masuk_kg', 'berat_terpakai_kg'):
        op.alter_column('polishing_silo_usage', kolom, type_=sa.Numeric(12, 2))
    op.drop_column('pk_purchase_batches', 'ukuran_karung_kg')
    op.drop_column('pk_purchase_batches', 'jumlah_karung')
