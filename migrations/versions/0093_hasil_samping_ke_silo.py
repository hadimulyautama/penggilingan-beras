"""Catat perpindahan stok menir/reject ke silo."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0093_hasil_samping_ke_silo"
down_revision: Union[str, None] = "0092_pengaturan_gudang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hasil_samping_ke_silo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode_pindah", sa.String(20), nullable=False, unique=True),
        sa.Column("polishing_process_id", sa.Integer(),
                  sa.ForeignKey("polishing_process.id"), nullable=False),
        sa.Column("jenis", sa.String(20), nullable=False),
        sa.Column("silo_id", sa.Integer(), sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jasa_id", sa.Integer(), sa.ForeignKey("jasa.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_hasil_samping_ke_silo_owner_jenis", "hasil_samping_ke_silo",
                    ["jasa_id", "jenis"])


def downgrade() -> None:
    op.drop_index("ix_hasil_samping_ke_silo_owner_jenis", table_name="hasil_samping_ke_silo")
    op.drop_table("hasil_samping_ke_silo")
