"""Master organisasi kosong; tanpa mengubah atau mengaitkan data bisnis lama.

Kontrak ORM milik core. Chain PadiFlow menjalankan DDL selama pelari master
belum dipindahkan; TeraFlow hanya membaca dan tidak membuat tabel tandingan.
"""
from alembic import op
import sqlalchemy as sa

revision = '0128_master_organisasi'
down_revision = '0127_transfer_tanpa_kendaraan'
branch_labels = depends_on = None
TABEL = ('hmu_warehouse_sites', 'hmu_company_memberships', 'hmu_factory_sites', 'hmu_companies')


def waktu():
    return [sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table('hmu_companies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kode', sa.String(50), nullable=False, unique=True),
        sa.Column('nama', sa.String(200), nullable=False),
        sa.Column('aktif', sa.Boolean(), server_default=sa.true(), nullable=False),
        *waktu(),
        sa.CheckConstraint('length(trim(kode)) > 0', name='ck_hmu_companies_kode'),
        sa.CheckConstraint('length(trim(nama)) > 0', name='ck_hmu_companies_nama'))
    op.create_table('hmu_factory_sites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('hmu_companies.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('kode', sa.String(50), nullable=False),
        sa.Column('nama', sa.String(200), nullable=False),
        sa.Column('alamat', sa.Text()),
        sa.Column('aktif', sa.Boolean(), server_default=sa.true(), nullable=False),
        *waktu(),
        sa.UniqueConstraint('company_id', 'kode', name='uq_hmu_sites_company_kode'),
        sa.UniqueConstraint('id', 'company_id', name='uq_hmu_sites_id_company'),
        sa.CheckConstraint('length(trim(kode)) > 0', name='ck_hmu_sites_kode'),
        sa.CheckConstraint('length(trim(nama)) > 0', name='ck_hmu_sites_nama'))
    op.create_table('hmu_company_memberships',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('hmu_companies.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('peran', sa.String(20), nullable=False),
        sa.Column('aktif', sa.Boolean(), server_default=sa.true(), nullable=False),
        *waktu(),
        sa.UniqueConstraint('company_id', 'user_id', name='uq_hmu_memberships_company_user'),
        sa.CheckConstraint('length(trim(peran)) > 0', name='ck_hmu_memberships_peran'))
    op.create_index('ix_hmu_memberships_user', 'hmu_company_memberships', ['user_id'])
    op.create_table('hmu_warehouse_sites',
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='RESTRICT'), primary_key=True, autoincrement=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('hmu_companies.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('lokasi_pabrik_id', sa.Integer(), nullable=False),
        *waktu(),
        sa.ForeignKeyConstraint(['lokasi_pabrik_id', 'company_id'], ['hmu_factory_sites.id', 'hmu_factory_sites.company_id'],
            name='fk_hmu_warehouse_site_company', ondelete='RESTRICT'))
    op.create_index('ix_hmu_warehouse_sites_lokasi', 'hmu_warehouse_sites', ['lokasi_pabrik_id', 'company_id'])


def downgrade():
    # Rollback kode lama tetap aman dengan tabel ini dibiarkan ada. Bila
    # master sudah dipakai, jangan hapus identitas atau keanggotaannya.
    for tabel in TABEL:
        if op.get_bind().execute(sa.text(f'SELECT 1 FROM {tabel} LIMIT 1')).first():
            raise RuntimeError('Master organisasi sudah terisi; rollback skema tidak boleh menghapus identitasnya.')
    for tabel in TABEL:
        op.drop_table(tabel)
