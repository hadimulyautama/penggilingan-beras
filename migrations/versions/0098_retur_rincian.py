"""Rincian kemasan retur Produksi sebelum penyelesaian timbang kedua."""
from alembic import op
import sqlalchemy as sa

revision = '0098_retur_rincian'
down_revision = '0097_urut_beras_ke_silo'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('kemasan_tara',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('packaging_material_id', sa.Integer(), sa.ForeignKey('packaging_materials.id'), nullable=False),
        sa.Column('package_size_id', sa.Integer(), sa.ForeignKey('package_sizes.id'), nullable=False),
        sa.Column('tara_per_karung_kg', sa.Numeric(10, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('packaging_material_id', 'package_size_id'),
    )
    # Nilai kesepakatan pemilik dibekukan dalam migrasi agar replay stabil.
    op.execute(sa.text("""INSERT INTO kemasan_tara
        (packaging_material_id, package_size_id, tara_per_karung_kg)
        SELECT m.id, s.id, v.tara FROM (VALUES
            ('biasa', 5, 0.03),
            ('biasa', 10, 0.05),
            ('biasa', 20, 0.05),
            ('biasa', 25, 0.05),
            ('biasa', 40, 0.07),
            ('biasa', 48, 0.07),
            ('biasa', 50, 0.07),
            ('laminasi', 5, 0.03),
            ('laminasi', 10, 0.05),
            ('laminasi', 20, 0.07),
            ('laminasi', 25, 0.08),
            ('putih', 50, 0.07),
            ('polos', 25, 0.05),
            ('bekas', 20, 0.05),
            ('bekas', 40, 0.07),
            ('bekas', 50, 0.07),
            ('karung_pk', 50, 0.07)
        ) AS v(kode, ukuran, tara)
        JOIN packaging_materials m ON m.kode=v.kode
        JOIN package_sizes s ON s.ukuran_kg=v.ukuran"""))
    op.create_table(
        'retur_rincian',
        sa.Column('id', sa.Integer(), primary_key=True),
        # Tiket dimiliki rantai migrasi Timbangan; seperti customer_returns,
        # ikatan lintas layanan ini tidak memperkenalkan FK baru.
        sa.Column('timbangan_transaksi_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('muatan', sa.JSON(), nullable=False),
        sa.Column('input_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('retur_rincian')
    op.drop_table('kemasan_tara')
