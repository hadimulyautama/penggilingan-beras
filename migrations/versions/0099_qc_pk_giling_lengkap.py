"""QC PK hasil giling mencatat butir kuning, gabah, merang dan catatan lab."""
from alembic import op
import sqlalchemy as sa

revision = "0099_qc_pk_giling_lengkap"
down_revision = "0098_retur_rincian"
branch_labels = None
depends_on = None


def upgrade():
    # NULL pada catatan lama berarti belum dinilai; jangan mengisinya Bersih.
    for medan in ("butir_kuning", "gabah", "merang"):
        op.add_column("milling_qc_logs", sa.Column(medan, sa.String(10), nullable=True))
    op.add_column("milling_qc_logs", sa.Column("catatan_lab", sa.String(255), nullable=True))


def downgrade():
    for medan in ("catatan_lab", "merang", "gabah", "butir_kuning"):
        op.drop_column("milling_qc_logs", medan)
