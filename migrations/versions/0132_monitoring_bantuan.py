"""Metadata monitoring dan bantuan. Tanpa backfill atau UPDATE transaksi lama."""
from alembic import op
import sqlalchemy as sa
revision='0132_monitoring_bantuan'
down_revision='0131_ruang_perusahaan'
branch_labels=depends_on=None

def upgrade():
    op.create_table('hmu_monitoring_sources',
      sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id'),primary_key=True),
      sa.Column('aplikasi',sa.String(16),primary_key=True),
      sa.Column('mulai',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
      sa.Column('terakhir',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
      sa.Column('versi',sa.String(64),nullable=False))
    op.create_table('hmu_usage_events',sa.Column('id',sa.Integer(),primary_key=True),
      sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id'),nullable=False),
      sa.Column('aplikasi',sa.String(16),nullable=False),sa.Column('event_id',sa.String(36),nullable=False),
      sa.Column('jenis_akun',sa.String(20),nullable=False),sa.Column('akun_id',sa.Integer(),nullable=False),
      sa.Column('user_id',sa.Integer()),sa.Column('peran',sa.String(24),nullable=False),sa.Column('warehouse_id',sa.Integer()),
      sa.Column('jenis',sa.String(24),nullable=False),sa.Column('layar',sa.String(40),nullable=False),
      sa.Column('kode',sa.String(40),nullable=False),sa.Column('metode',sa.String(8),nullable=False),sa.Column('browser',sa.String(20),nullable=False),
      sa.Column('perangkat',sa.String(20),nullable=False),sa.Column('durasi_ms',sa.Integer()),
      sa.Column('waktu',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
      sa.UniqueConstraint('company_id','aplikasi','event_id',name='uq_hmu_usage_event'))
    op.create_index('ix_hmu_usage_time','hmu_usage_events',['company_id','waktu'])
    op.create_index('ix_hmu_usage_subject','hmu_usage_events',['company_id','jenis_akun','akun_id','waktu'])
    op.create_table('hmu_login_unlocks',sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id'),primary_key=True),
      sa.Column('jenis_akun',sa.String(20),primary_key=True),sa.Column('akun_id',sa.Integer(),primary_key=True),sa.Column('generasi',sa.Integer(),nullable=False))
    op.create_table('hmu_support_plans',sa.Column('id',sa.String(36),primary_key=True),
      sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id'),nullable=False),
      sa.Column('pelaku_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
      sa.Column('jenis_akun',sa.String(20),nullable=False),sa.Column('akun_id',sa.Integer(),nullable=False),
      sa.Column('aksi',sa.String(32),nullable=False),sa.Column('alasan',sa.Text(),nullable=False),
      sa.Column('sidik',sa.String(64),nullable=False),sa.Column('sebelum',sa.Text(),nullable=False),
      sa.Column('kedaluwarsa',sa.DateTime(timezone=True),nullable=False),sa.Column('diterapkan',sa.DateTime(timezone=True)),sa.Column('hasil',sa.Text()))
    op.create_table('hmu_account_recoveries',sa.Column('id',sa.String(36),primary_key=True),
      sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id'),nullable=False),
      sa.Column('jenis_akun',sa.String(20),nullable=False),sa.Column('akun_id',sa.Integer(),nullable=False),
      sa.Column('cap_hash',sa.String(64),nullable=False,unique=True),sa.Column('versi',sa.Integer(),nullable=False),
      sa.Column('kedaluwarsa',sa.DateTime(timezone=True),nullable=False),sa.Column('dipakai',sa.DateTime(timezone=True)),
      sa.Column('dicabut',sa.Boolean(),nullable=False),sa.Column('pelaku_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False))


def downgrade():
    for name in ('hmu_account_recoveries','hmu_support_plans','hmu_login_unlocks','hmu_usage_events','hmu_monitoring_sources'):
        if op.get_bind().execute(sa.text('SELECT 1 FROM '+name+' LIMIT 1')).first():
            raise RuntimeError('Metadata monitoring/bantuan sudah terisi; audit dan statistik tidak boleh dihapus melalui downgrade.')
    for name in ('hmu_account_recoveries','hmu_support_plans','hmu_login_unlocks','hmu_usage_events','hmu_monitoring_sources'):op.drop_table(name)
