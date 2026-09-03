"""Proses giling punya DAFTAR ISI sendiri (Fase B — pemisahan lot).

Sampai sekarang `milling_process` menunjuk SATU sumber: satu baris silo, dan
lewat itu satu lot atau satu batch. Itu cukup selama satu silo hanya boleh
berisi satu hal. Begitu silo boleh dicampur — lot hasil pengeringan ditambah
batch kering yang masuk belakangan — penunjuk tunggal itu diam-diam memilih
salah satu dan mengabaikan sisanya: gabahnya tergiling, tetapi tidak tercatat.

Tabel ini memisahkan dua arti yang selama ini dipaksa jadi satu:

  · `drying_lots` tetap berarti SATU PROSES PENGERINGAN — dryer mana, kurva
    kadar airnya, berapa putaran pendinginan;
  · proses giling berarti APA YANG DIGILING BERSAMA, dan isinya didaftar di
    sini, satu baris per sumber.

Kolom lama di `milling_process` sengaja DIBIARKAN: laporan, undo, dan
rekonsiliasi masih membacanya, dan mencabutnya sekaligus akan mematikan
semuanya dalam satu langkah. Ia kini berisi sumber UTAMA; kebenaran beratnya
ada di tabel ini.

Revision ID: 0031_isi_giling
Revises: 0030_produksi_akun
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_isi_giling"
down_revision: Union[str, None] = "0030_produksi_akun"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "milling_process_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("milling_process_id", sa.Integer(), nullable=False),
        sa.Column("silo_storage_id", sa.Integer(), nullable=False),
        # Tepat satu dari dua ini terisi — sama seperti di `silo_storage`,
        # karena baris silo memang berisi salah satunya.
        sa.Column("drying_lot_id", sa.Integer(), nullable=True),
        sa.Column("purchase_batch_id", sa.Integer(), nullable=True),
        sa.Column("berat_kg", sa.Numeric(12, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["milling_process_id"], ["milling_process.id"],
                                name="fk_mps_proses", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["silo_storage_id"], ["silo_storage.id"], name="fk_mps_silo"),
        sa.ForeignKeyConstraint(["drying_lot_id"], ["drying_lots.id"], name="fk_mps_lot"),
        sa.ForeignKeyConstraint(["purchase_batch_id"], ["purchase_batches.id"],
                                name="fk_mps_batch"),
        sa.PrimaryKeyConstraint("id"),
        # Satu baris silo tidak boleh masuk dua kali ke proses yang sama.
        sa.UniqueConstraint("milling_process_id", "silo_storage_id", name="uq_mps_proses_silo"),
    )
    op.create_index("ix_mps_proses", "milling_process_sources", ["milling_process_id"])

    # Proses giling yang SUDAH ADA diberi daftar isi dari penunjuk tunggalnya,
    # supaya tabel ini langsung menjadi kebenaran untuk semua — bukan hanya
    # untuk yang dibuat setelah hari ini. Tanpa ini, laporan yang membaca
    # tabel baru akan melihat riwayat kosong.
    op.execute("""
        INSERT INTO milling_process_sources
              (milling_process_id, silo_storage_id, drying_lot_id,
               purchase_batch_id, berat_kg)
        SELECT p.id, p.silo_storage_id, p.drying_lot_id, p.purchase_batch_id,
               COALESCE(p.berat_gabah_masuk_kg, 0)
          FROM milling_process p
         WHERE p.silo_storage_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_mps_proses", table_name="milling_process_sources")
    op.drop_table("milling_process_sources")
