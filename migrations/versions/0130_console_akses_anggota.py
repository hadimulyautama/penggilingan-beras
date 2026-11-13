"""Fondasi akses eksplisit dan sesi Console; tanpa backfill atau perubahan transaksi."""
from alembic import op
import sqlalchemy as sa
revision='0130_console_akses_anggota'
down_revision='0129_koreksi_transfer_pk'
branch_labels=depends_on=None
TABEL=('hmu_membership_warehouses','hmu_membership_sites','hmu_console_sessions')


def waktu():
    return [sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
            sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now())]


def upgrade():
    op.create_unique_constraint('uq_hmu_memberships_id_company','hmu_company_memberships',['id','company_id'])
    op.create_unique_constraint('uq_hmu_warehouse_site_company','hmu_warehouse_sites',['warehouse_id','lokasi_pabrik_id','company_id'])
    op.create_table('hmu_membership_sites',
        sa.Column('keanggotaan_id',sa.Integer(),primary_key=True,autoincrement=False),
        sa.Column('lokasi_pabrik_id',sa.Integer(),primary_key=True,autoincrement=False),
        sa.Column('company_id',sa.Integer(),nullable=False),
        sa.Column('semua_gudang',sa.Boolean(),nullable=False,server_default=sa.false()),*waktu(),
        sa.ForeignKeyConstraint(['keanggotaan_id','company_id'],['hmu_company_memberships.id','hmu_company_memberships.company_id'],ondelete='RESTRICT',name='fk_hmu_member_site_membership'),
        sa.ForeignKeyConstraint(['lokasi_pabrik_id','company_id'],['hmu_factory_sites.id','hmu_factory_sites.company_id'],ondelete='RESTRICT',name='fk_hmu_member_site_company'),
        sa.UniqueConstraint('keanggotaan_id','lokasi_pabrik_id','company_id',name='uq_hmu_member_site_company'))
    op.create_table('hmu_membership_warehouses',
        sa.Column('keanggotaan_id',sa.Integer(),primary_key=True,autoincrement=False),
        sa.Column('warehouse_id',sa.Integer(),primary_key=True,autoincrement=False),
        sa.Column('lokasi_pabrik_id',sa.Integer(),nullable=False),sa.Column('company_id',sa.Integer(),nullable=False),*waktu(),
        sa.ForeignKeyConstraint(['keanggotaan_id','lokasi_pabrik_id','company_id'],['hmu_membership_sites.keanggotaan_id','hmu_membership_sites.lokasi_pabrik_id','hmu_membership_sites.company_id'],ondelete='RESTRICT',name='fk_hmu_member_warehouse_site'),
        sa.ForeignKeyConstraint(['warehouse_id','lokasi_pabrik_id','company_id'],['hmu_warehouse_sites.warehouse_id','hmu_warehouse_sites.lokasi_pabrik_id','hmu_warehouse_sites.company_id'],ondelete='RESTRICT',name='fk_hmu_member_warehouse_binding'))
    op.create_table('hmu_console_sessions',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('akun_id',sa.Integer(),sa.ForeignKey('produksi_akun.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('versi',sa.Integer(),nullable=False),sa.Column('kode_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('tantangan',sa.String(43),nullable=False),sa.Column('kode_sampai',sa.DateTime(timezone=True),nullable=False),
        sa.Column('token_hash',sa.String(64),unique=True),sa.Column('sesi_sampai',sa.DateTime(timezone=True)),
        sa.Column('ditukar_pada',sa.DateTime(timezone=True)),sa.Column('dicabut',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('dibuat_pada',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))


def downgrade():
    for t in TABEL:
        if op.get_bind().execute(sa.text('SELECT 1 FROM '+t+' LIMIT 1')).first():
            raise RuntimeError('Akses atau sesi Console sudah terisi; rollback skema tidak boleh menghapusnya.')
    for t in TABEL:op.drop_table(t)
    op.drop_constraint('uq_hmu_warehouse_site_company','hmu_warehouse_sites',type_='unique')
    op.drop_constraint('uq_hmu_memberships_id_company','hmu_company_memberships',type_='unique')
