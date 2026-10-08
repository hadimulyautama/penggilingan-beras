"""Gabah kering dikemas & ditimbang — jalan keluar keempat dari silo G1.

Pesan kerja 7 Oktober 2026, butir 6 (rinci PESAN-KERJA-12 + 12A + 12B, dengan
PESAN-KERJA-12 bagian 3 DICABUT SELURUHNYA oleh 12A: gabah tak punya ukuran
karung baku, jadi ia TETAP bahan — tidak pernah masuk `finished_goods_stock`).

Tiga perubahan, lahir bersamaan karena ketiganya satu fitur:

  1. `silo_storage.dikemas_kg` — suku KELUAR baru dari silo (selain giling).
     Tanpa ini "jalan masuk/keluar baru wajib lahir bersama suku
     hitungannya" dilanggar lagi — pola yang sudah tiga kali terjadi (pesan
     8, pesan 11, dan ini).
  2. `gabah_kering_lots` — satu KELUARAN gabah dari silo, ditimbang (SATU
     angka global, bukan per karung), re-weigh-able (berat_timbang_kg
     DIGANTI di tempat, bukan riwayat yang dijumlah — pesan 12B). Jalan
     keluarnya meniru `pk_langsung`: tanpa SKU, tanpa jumlah karung wajib.
  3. `gabah_kering_bongkar` — satu kali lot ini dibongkar KEMBALI ke silo
     (whole-lot). `outgoing_items.gabah_kering_lot_id` — jenis barang baru
     `gabah_langsung` di perintah keluar, untuk diambil pemiliknya (jasa)
     atau dijual (pabrik).

Revision ID: 0077_gabah_kering_dikemas
Revises: 0076_pk_g2_keluar
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0077_gabah_kering_dikemas"
down_revision: Union[str, None] = "0076_pk_g2_keluar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("silo_storage", sa.Column(
        "dikemas_kg", sa.Numeric(12, 2), nullable=False, server_default="0"))

    op.create_table(
        "gabah_kering_lots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode_lot", sa.String(20), nullable=False, unique=True),
        sa.Column("silo_storage_id", sa.Integer(),
                  sa.ForeignKey("silo_storage.id"), nullable=False),
        sa.Column("jasa_id", sa.Integer(), sa.ForeignKey("jasa.id"), nullable=True),
        sa.Column("berat_timbang_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("jumlah_karung", sa.Integer(), nullable=True),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu_timbang", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_gabah_kering_lots_jasa", "gabah_kering_lots", ["jasa_id"],
        postgresql_where=sa.text("jasa_id IS NOT NULL"),
        sqlite_where=sa.text("jasa_id IS NOT NULL"))

    op.create_table(
        "gabah_kering_bongkar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode_pindah", sa.String(20), nullable=False, unique=True),
        sa.Column("gabah_kering_lot_id", sa.Integer(),
                  sa.ForeignKey("gabah_kering_lots.id"), nullable=False),
        sa.Column("silo_storage_id", sa.Integer(),
                  sa.ForeignKey("silo_storage.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    op.add_column("outgoing_items", sa.Column(
        "gabah_kering_lot_id", sa.Integer(),
        sa.ForeignKey("gabah_kering_lots.id"), nullable=True))
    op.create_index("ix_outgoing_items_gabah_kering_lot", "outgoing_items",
                    ["gabah_kering_lot_id"])


def downgrade() -> None:
    op.drop_index("ix_outgoing_items_gabah_kering_lot", table_name="outgoing_items")
    op.drop_column("outgoing_items", "gabah_kering_lot_id")
    op.drop_table("gabah_kering_bongkar")
    op.drop_index("ix_gabah_kering_lots_jasa", table_name="gabah_kering_lots")
    op.drop_table("gabah_kering_lots")
    op.drop_column("silo_storage", "dikemas_kg")
