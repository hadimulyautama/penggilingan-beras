"""Proyeksi pemindahan PK G1 → G2 — aksi keempat di jalur peristiwa (Tahap 3).

`proyeksi_transfer_pk` diturunkan dari peristiwa `pk_dipindah_g1g2`;
`internal_transfers.peristiwa_id` penunjuk cermin. Cermin transfer tidak
dihapus saat dibatalkan (status `dibatalkan`). Hanya menambah.

Revision ID: 0050_peristiwa_transfer
Revises: 0049_peristiwa_pk_masuk_g2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050_peristiwa_transfer"
down_revision: Union[str, None] = "0049_peristiwa_pk_masuk_g2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proyeksi_transfer_pk",
        sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id"), primary_key=True),
        sa.Column("kode_transfer", sa.String(20), nullable=False),
        sa.Column("milling_process_id", sa.Integer()),
        sa.Column("kode_proses", sa.String(20)),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("lokasi_tujuan", sa.String(20), nullable=False),
        sa.Column("hpp_per_kg", sa.Numeric(12, 2)),
        sa.Column("jenis", sa.String(8)),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pelaku_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dibatalkan_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("intake_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("transfer_id", sa.Integer()),
        sa.CheckConstraint("berat_kg > 0", name="ck_proyeksi_transfer_pk_berat"),
        sa.CheckConstraint("status IN ('tercatat', 'dibatalkan')", name="ck_proyeksi_transfer_pk_status"),
        sa.CheckConstraint("lokasi_tujuan IN ('silo_a', 'silo_b', 'ditumpuk')",
                           name="ck_proyeksi_transfer_pk_tujuan"),
    )
    op.create_index("ix_proyeksi_transfer_pk_proses", "proyeksi_transfer_pk", ["milling_process_id"])
    op.add_column("internal_transfers",
                  sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")))


def downgrade() -> None:
    op.drop_column("internal_transfers", "peristiwa_id")
    op.drop_index("ix_proyeksi_transfer_pk_proses", table_name="proyeksi_transfer_pk")
    op.drop_table("proyeksi_transfer_pk")
