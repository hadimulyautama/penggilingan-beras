"""Pembatalan transfer generik menyimpan item nol, tanpa menghapus jejaknya."""
from alembic import op
import sqlalchemy as sa

revision = '0129_koreksi_transfer_pk'
down_revision = '0128_master_organisasi'
branch_labels = depends_on = None


def upgrade():
    op.drop_constraint('ck_pengiriman_pk_kendaraan', 'pengiriman_pk', type_='check')
    op.create_check_constraint('ck_pengiriman_pk_kendaraan', 'pengiriman_pk',
        "(pakai_kendaraan AND nomor_polisi IS NOT NULL AND nama_sopir IS NOT NULL) OR (NOT pakai_kendaraan AND nomor_polisi IS NULL AND nama_sopir IS NULL AND tiket_id IS NULL AND status IN ('selesai','dibatalkan'))")
    op.drop_constraint('ck_pengiriman_pk_item_positif', 'pengiriman_pk_items', type_='check')
    op.create_check_constraint('ck_pengiriman_pk_item_positif', 'pengiriman_pk_items', 'berat_kg >= 0')


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM pengiriman_pk_items WHERE berat_kg=0 LIMIT 1")).first():
        raise RuntimeError('Koreksi pembatalan sudah tercatat; rollback tidak boleh menghapus jejaknya.')
    op.drop_constraint('ck_pengiriman_pk_item_positif', 'pengiriman_pk_items', type_='check')
    op.create_check_constraint('ck_pengiriman_pk_item_positif', 'pengiriman_pk_items', 'berat_kg > 0')
    op.drop_constraint('ck_pengiriman_pk_kendaraan', 'pengiriman_pk', type_='check')
    op.create_check_constraint('ck_pengiriman_pk_kendaraan', 'pengiriman_pk',
        "(pakai_kendaraan AND nomor_polisi IS NOT NULL AND nama_sopir IS NOT NULL) OR (NOT pakai_kendaraan AND nomor_polisi IS NULL AND nama_sopir IS NULL AND tiket_id IS NULL AND status = 'selesai')")
