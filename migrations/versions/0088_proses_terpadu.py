"""Buat identitas dan arus proses bersama lintas aplikasi.

Revision ID: 0088_proses_terpadu
Revises: 0087_armada_bersama
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0088_proses_terpadu"
down_revision: Union[str, None] = "0087_armada_bersama"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "proses_terpadu" not in tables:
        op.create_table(
            "proses_terpadu",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("aplikasi", sa.String(30), nullable=False),
            sa.Column("tabel_sumber", sa.String(80), nullable=False),
            sa.Column("id_sumber", sa.String(80), nullable=False),
            sa.Column("kode", sa.String(80), nullable=False),
            sa.Column("jenis", sa.String(40), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("jenis_pemilik", sa.String(20), nullable=False),
            sa.Column("id_pemilik", sa.Integer()),
            sa.Column("nama_pemilik", sa.String(160)),
            sa.Column("waktu_mulai", sa.DateTime(timezone=True)),
            sa.Column("waktu_selesai", sa.DateTime(timezone=True)),
            sa.Column("pelaksana_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("referensi_asal", sa.JSON(), nullable=False,
                      server_default=sa.text("'[]'")),
            sa.Column("metadata_domain", sa.JSON(), nullable=False,
                      server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.UniqueConstraint("aplikasi", "tabel_sumber", "id_sumber",
                                name="uq_proses_terpadu_sumber"),
            sa.CheckConstraint(
                "status IN ('menunggu','berjalan','dihentikan','selesai','dibatalkan')",
                name="ck_proses_terpadu_status"),
        )
        op.create_index("ix_proses_terpadu_jenis_status", "proses_terpadu",
                        ["jenis", "status"])
        op.create_index("ix_proses_terpadu_pemilik", "proses_terpadu",
                        ["jenis_pemilik", "id_pemilik"])

    tables = set(sa.inspect(bind).get_table_names())
    if "arus_proses_terpadu" not in tables:
        op.create_table(
            "arus_proses_terpadu",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("proses_id", sa.Integer(),
                      sa.ForeignKey("proses_terpadu.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("arah", sa.String(10), nullable=False),
            sa.Column("komoditas", sa.String(40), nullable=False),
            sa.Column("atribut_produk", sa.JSON(), nullable=False,
                      server_default=sa.text("'{}'")),
            sa.Column("berat_kg", sa.Numeric(14, 2), nullable=False),
            sa.Column("referensi", sa.String(100)),
            sa.Column("lokasi_id", sa.Integer()),
            sa.Column("detail", sa.JSON(), nullable=False,
                      server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.CheckConstraint("arah IN ('bahan','hasil')",
                               name="ck_arus_proses_arah"),
            sa.CheckConstraint("berat_kg >= 0",
                               name="ck_arus_proses_berat_nonnegatif"),
        )
        op.create_index("ix_arus_proses_terpadu_proses", "arus_proses_terpadu",
                        ["proses_id", "arah"])


def downgrade() -> None:
    # Data proses lintas aplikasi bersifat jejak; tidak dihapus otomatis.
    pass
