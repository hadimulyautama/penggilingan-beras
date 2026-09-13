"""Proyeksi PK masuk Gudang 2 — aksi ketiga di jalur peristiwa (Tahap 3, P-K-10).

`proyeksi_pk_masuk_g2` diturunkan dari peristiwa `pk_masuk_g2` (PK masuk ke
silo/tumpukan, dari PK luar maupun transfer G1); `pk_gudang2_intakes.
peristiwa_id` penunjuk cermin. Hanya menambah; baris yang ada dibiarkan
kosong (jalur lama).

Revision ID: 0049_peristiwa_pk_masuk_g2
Revises: 0048_peristiwa_pk_luar
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049_peristiwa_pk_masuk_g2"
down_revision: Union[str, None] = "0048_peristiwa_pk_luar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proyeksi_pk_masuk_g2",
        sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id"), primary_key=True),
        sa.Column("sumber_tipe", sa.String(20), nullable=False),
        sa.Column("pk_purchase_batch_id", sa.Integer()),
        sa.Column("internal_transfer_id", sa.Integer()),
        sa.Column("tujuan", sa.String(20), nullable=False),
        sa.Column("silo_id", sa.Integer(), sa.ForeignKey("silos.id")),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("hpp_per_kg", sa.Numeric(12, 2)),
        sa.Column("ke_proses", sa.String(20)),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pelaku_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dibatalkan_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("intake_id", sa.Integer()),
        sa.CheckConstraint("berat_kg >= 0", name="ck_proyeksi_pk_masuk_g2_berat"),
        sa.CheckConstraint("status IN ('tercatat', 'dibatalkan')", name="ck_proyeksi_pk_masuk_g2_status"),
        sa.CheckConstraint("tujuan IN ('silo_a', 'silo_b', 'ditumpuk')", name="ck_proyeksi_pk_masuk_g2_tujuan"),
    )
    op.create_index("uq_proyeksi_pk_masuk_g2_batch_hidup", "proyeksi_pk_masuk_g2",
                    ["pk_purchase_batch_id"], unique=True,
                    postgresql_where=sa.text("status = 'tercatat' AND pk_purchase_batch_id IS NOT NULL"))
    op.create_index("uq_proyeksi_pk_masuk_g2_transfer_hidup", "proyeksi_pk_masuk_g2",
                    ["internal_transfer_id"], unique=True,
                    postgresql_where=sa.text("status = 'tercatat' AND internal_transfer_id IS NOT NULL"))
    op.create_index("ix_proyeksi_pk_masuk_g2_silo", "proyeksi_pk_masuk_g2", ["silo_id"])
    op.add_column("pk_gudang2_intakes",
                  sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")))


def downgrade() -> None:
    op.drop_column("pk_gudang2_intakes", "peristiwa_id")
    op.drop_index("ix_proyeksi_pk_masuk_g2_silo", table_name="proyeksi_pk_masuk_g2")
    op.drop_index("uq_proyeksi_pk_masuk_g2_transfer_hidup", table_name="proyeksi_pk_masuk_g2")
    op.drop_index("uq_proyeksi_pk_masuk_g2_batch_hidup", table_name="proyeksi_pk_masuk_g2")
    op.drop_table("proyeksi_pk_masuk_g2")
