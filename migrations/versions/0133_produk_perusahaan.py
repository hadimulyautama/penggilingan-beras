"""Aktivasi produk dan akses terpisah; hanya tabel metadata baru."""
from alembic import op
import sqlalchemy as sa
revision='0133_produk_perusahaan'
down_revision='0132_monitoring_bantuan'
branch_labels=depends_on=None

def waktu():
    return [sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now())]

def upgrade():
    op.create_table('hmu_company_products',sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id',ondelete='RESTRICT'),primary_key=True),sa.Column('produk',sa.String(30),primary_key=True),sa.Column('aktif',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('warisan',sa.Boolean(),nullable=False,server_default=sa.false()),*waktu(),sa.CheckConstraint("produk IN ('padiflow','teraflow')",name='ck_hmu_company_products_code'))
    op.create_table('hmu_member_products',sa.Column('company_id',sa.Integer(),primary_key=True),sa.Column('user_id',sa.Integer(),primary_key=True),sa.Column('produk',sa.String(30),primary_key=True),sa.Column('aktif',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('peran',sa.String(20),nullable=False),*waktu(),sa.ForeignKeyConstraint(['company_id','produk'],['hmu_company_products.company_id','hmu_company_products.produk'],ondelete='RESTRICT',name='fk_hmu_member_product_company'),sa.ForeignKeyConstraint(['company_id','user_id'],['hmu_company_memberships.company_id','hmu_company_memberships.user_id'],ondelete='RESTRICT',name='fk_hmu_member_product_membership'),sa.CheckConstraint("peran IN ('admin','operator')",name='ck_hmu_member_products_role'))
    op.create_table('hmu_company_integrations',sa.Column('company_id',sa.Integer(),sa.ForeignKey('hmu_companies.id',ondelete='RESTRICT'),primary_key=True),sa.Column('kode',sa.String(50),primary_key=True),sa.Column('aktif',sa.Boolean(),nullable=False,server_default=sa.false()),*waktu(),sa.CheckConstraint("kode='padiflow_teraflow'",name='ck_hmu_company_integrations_code'))
    # Tidak menebak perusahaan dari ID pertama/nama. Dua penetapan metadata
    # lama harus menunjuk perusahaan yang sama sebelum akses HMU diwariskan.
    op.execute("""INSERT INTO hmu_company_products(company_id,produk,aktif,warisan)
      SELECT c.id,p.kode,true,true FROM hmu_companies c
      JOIN setelan_pabrik r ON r.kunci='ruang_data_perusahaan' AND (r.nilai::jsonb->>'company_id')::int=c.id
      JOIN setelan_pabrik l ON l.kunci='organisasi_perusahaan_lama' AND (l.nilai::jsonb->>'company_id')::int=c.id
      CROSS JOIN (VALUES ('padiflow'),('teraflow')) p(kode)""")
    op.execute("""INSERT INTO hmu_company_integrations(company_id,kode,aktif)
      SELECT company_id,'padiflow_teraflow',true FROM hmu_company_products WHERE produk='padiflow' AND warisan""")

def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM hmu_company_products LIMIT 1')).first():
        raise RuntimeError('Metadata produk sudah digunakan; pulihkan kode tanpa menghapus penetapan akses.')
    op.drop_table('hmu_member_products');op.drop_table('hmu_company_integrations');op.drop_table('hmu_company_products')
