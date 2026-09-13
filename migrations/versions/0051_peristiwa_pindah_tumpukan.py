"""Proyeksi pindah tumpukan → silo — aksi kelima di jalur peristiwa (Tahap 3).

`proyeksi_pindah_tumpukan_silo` diturunkan dari peristiwa `pk_tumpukan_ke_silo`;
`pk_tumpukan_to_silo.peristiwa_id` penunjuk cermin. Hanya menambah.

Revision ID: 0051_peristiwa_pindah_tumpukan
Revises: 0050_peristiwa_transfer
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051_peristiwa_pindah_tumpukan"
down_revision: Union[str, None] = "0050_peristiwa_transfer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proyeksi_pindah_tumpukan_silo",
        sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id"), primary_key=True),
        sa.Column("kode_pindah", sa.String(20), nullable=False),
        sa.Column("intake_id", sa.Integer(), nullable=False),
        sa.Column("intake_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("silo_id", sa.Integer(), sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("ke_proses", sa.String(20)),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pelaku_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dibatalkan_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("move_id", sa.Integer()),
        sa.CheckConstraint("berat_kg > 0", name="ck_proyeksi_pindah_tumpukan_silo_berat"),
        sa.CheckConstraint("status IN ('tercatat', 'dibatalkan')",
                           name="ck_proyeksi_pindah_tumpukan_silo_status"),
    )
    op.create_index("ix_proyeksi_pindah_tumpukan_silo_intake", "proyeksi_pindah_tumpukan_silo", ["intake_id"])
    op.create_index("ix_proyeksi_pindah_tumpukan_silo_silo", "proyeksi_pindah_tumpukan_silo", ["silo_id"])
    op.add_column("pk_tumpukan_to_silo",
                  sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")))


def downgrade() -> None:
    op.drop_column("pk_tumpukan_to_silo", "peristiwa_id")
    op.drop_index("ix_proyeksi_pindah_tumpukan_silo_silo", table_name="proyeksi_pindah_tumpukan_silo")
    op.drop_index("ix_proyeksi_pindah_tumpukan_silo_intake", table_name="proyeksi_pindah_tumpukan_silo")
    op.drop_table("proyeksi_pindah_tumpukan_silo")
