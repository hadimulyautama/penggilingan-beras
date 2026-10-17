"""QC PK luar menjadi putaran berulang; pertahankan hasil lama sebagai log."""
from alembic import op
import sqlalchemy as sa

revision = "0100_qc_pk_luar_berulang"
down_revision = "0099_qc_pk_giling_lengkap"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("pk_purchase_qc_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pk_purchase_batch_id", sa.Integer(), sa.ForeignKey("pk_purchase_batches.id"), nullable=False),
        sa.Column("kadar_air", sa.Numeric(5, 2)),
        sa.Column("broken_persen", sa.Numeric(5, 2)),
        sa.Column("susut_persen", sa.Numeric(5, 2)),
        sa.Column("butir_kuning", sa.String(10)),
        sa.Column("gabah", sa.String(10)),
        sa.Column("merang", sa.String(10)),
        sa.Column("catatan_lab", sa.String(255)),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("asal_lama", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_pk_qc_batch", "pk_purchase_qc_logs", ["pk_purchase_batch_id"])
    # Hanya hasil yang masih tersimpan dapat dipertahankan. Jangan mengarang
    # putaran sebelum hasil ini atau memakai penetap harga sebagai petugas QC.
    op.execute(sa.text("""INSERT INTO pk_purchase_qc_logs
        (pk_purchase_batch_id,kadar_air,broken_persen,susut_persen,
         butir_kuning,gabah,merang,catatan_lab,waktu,input_by,asal_lama)
        SELECT pk_purchase_batch_id,kadar_air,broken_persen,penyusutan_persen,
               butir_kuning,gabah,merang,catatan_lab,updated_at,NULL,true
        FROM pk_purchase_verifications
        WHERE kadar_air IS NOT NULL OR broken_persen IS NOT NULL
           OR penyusutan_persen IS NOT NULL OR NULLIF(butir_kuning,'') IS NOT NULL
           OR NULLIF(gabah,'') IS NOT NULL OR NULLIF(merang,'') IS NOT NULL
           OR NULLIF(catatan_lab,'') IS NOT NULL"""))


def downgrade():
    # Snapshot tetap tersedia bagi versi aplikasi sebelumnya.
    op.drop_index("ix_pk_qc_batch", table_name="pk_purchase_qc_logs")
    op.drop_table("pk_purchase_qc_logs")
