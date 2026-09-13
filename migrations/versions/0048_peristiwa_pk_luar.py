"""Proyeksi PK luar masuk — aksi kedua di jalur peristiwa (Tahap 3).

Kembaran migrasi 0047 untuk Gudang 2: `proyeksi_pk_luar_masuk` diturunkan
dari peristiwa `pk_luar_masuk`; `pk_purchase_batches.peristiwa_id` penunjuk
cermin. Hanya menambah; baris yang ada dibiarkan kosong (jalur lama).

Revision ID: 0048_peristiwa_pk_luar
Revises: 0047_peristiwa
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_peristiwa_pk_luar"
down_revision: Union[str, None] = "0047_peristiwa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proyeksi_pk_luar_masuk",
        sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id"), primary_key=True),
        sa.Column("kode_batch", sa.String(20), nullable=False),
        sa.Column("timbangan_transaksi_id", sa.Integer()),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id")),
        sa.Column("nama_supplier", sa.String(150)),
        sa.Column("berat_kg", sa.Numeric(12, 2)),
        sa.Column("sumber_berat", sa.String(12), nullable=False),
        sa.Column("jenis_pk", sa.String(12)),
        sa.Column("kadar_air", sa.Numeric(5, 2)),
        sa.Column("no_polisi", sa.String(20)),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pelaku_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dibatalkan_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("pk_purchase_batch_id", sa.Integer()),
        sa.CheckConstraint("berat_kg IS NULL OR berat_kg >= 0", name="ck_proyeksi_pk_luar_masuk_berat"),
        sa.CheckConstraint("status IN ('tercatat', 'dibatalkan')", name="ck_proyeksi_pk_luar_masuk_status"),
    )
    op.create_index("uq_proyeksi_pk_luar_masuk_tiket_hidup", "proyeksi_pk_luar_masuk",
                    ["timbangan_transaksi_id"], unique=True,
                    postgresql_where=sa.text("status = 'tercatat'"))
    op.create_index("ix_proyeksi_pk_luar_masuk_tanggal", "proyeksi_pk_luar_masuk", ["tanggal"])
    op.add_column("pk_purchase_batches",
                  sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")))


def downgrade() -> None:
    op.drop_column("pk_purchase_batches", "peristiwa_id")
    op.drop_index("ix_proyeksi_pk_luar_masuk_tanggal", table_name="proyeksi_pk_luar_masuk")
    op.drop_index("uq_proyeksi_pk_luar_masuk_tiket_hidup", table_name="proyeksi_pk_luar_masuk")
    op.drop_table("proyeksi_pk_luar_masuk")
