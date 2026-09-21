"""Bobot yang belum ditimbang kedua kali — QA P6-01 s/d P6-04, 21 September 2026.

"Belum diketahui" bukan nol. Basis data sudah tahu itu sejak migrasi 0040
(`CHECK (berat_kg IS NULL OR berat_kg > 0)`), tetapi dua kolom tempat angka
itu bermuara masih NOT NULL, jadi giling dan PK luar yang truknya belum
ditimbang kedua ditolak dengan galat Postgres mentah.

Empat hal:

  * `purchase_batches.berat_perkiraan_kg`, `pk_purchase_batches.berat_perkiraan_kg`
    — perkiraan dari tara truk yang sama (timbang pertama − berat kosong
    terakhir nomor polisi itu). Disalin ke sini SELAIN ke `berat_total_kg`
    supaya, begitu netto sungguhan datang, selisihnya tetap bisa dihitung —
    "tara stabil" adalah anggapan lapangan yang harus bisa diuji dari data.
  * `milling_process.bobot_masuk_final` — false bila ada bahan yang masih
    perkiraan / belum diketahui saat giling dimulai. Poller membetulkan
    `berat_gabah_masuk_kg` proses seperti ini WALAU sudah selesai, dan
    rekonsiliasi menyebutnya sampai final.
  * `milling_process_sources.berat_kg` dan `pk_gudang2_intakes.berat_kg`
    (berikut proyeksinya) boleh NULL: bahan yang belum punya angka dicatat
    sebagai belum punya angka, bukan sebagai 0 — dan bukan ditolak.
  * `pk_gudang2_intakes.bobot_final` — false bila beratnya masih perkiraan /
    belum diketahui saat masuk; poller melengkapinya dari batch-nya.

Baris lama: giling yang salah satu bahannya masih 'menunggu' ditandai belum
final, supaya poller yang baru menjangkaunya tanpa ada yang mencatat ulang.

Revision ID: 0054_bobot_belum_final
Revises: 0053_activity_logs_gudang
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054_bobot_belum_final"
down_revision: Union[str, None] = "0053_activity_logs_gudang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for tabel in ("purchase_batches", "pk_purchase_batches"):
        op.add_column(tabel, sa.Column("berat_perkiraan_kg", sa.Numeric(12, 2), nullable=True))
    op.add_column("milling_process", sa.Column(
        "bobot_masuk_final", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("pk_gudang2_intakes", sa.Column(
        "bobot_final", sa.Boolean(), nullable=False, server_default=sa.true()))

    with op.batch_alter_table("milling_process_sources") as b:
        b.alter_column("berat_kg", existing_type=sa.Numeric(12, 3), nullable=True)
    with op.batch_alter_table("pk_gudang2_intakes") as b:
        b.alter_column("berat_kg", existing_type=sa.Numeric(12, 2), nullable=True)
    with op.batch_alter_table("proyeksi_pk_masuk_g2") as b:
        b.alter_column("berat_kg", existing_type=sa.Numeric(12, 2), nullable=True)

    # Giling yang bahannya masih menunggu bobot — sebelum ini hanya mungkin
    # bila dicampur dengan batch berbobot di satu lot (P6-03).
    op.execute("""
        UPDATE milling_process SET bobot_masuk_final = false
         WHERE id IN (
            SELECT s.milling_process_id
              FROM milling_process_sources s
              LEFT JOIN drying_lot_batches dlb ON dlb.drying_lot_id = s.drying_lot_id
              JOIN purchase_batches b
                ON b.id = COALESCE(s.purchase_batch_id, dlb.purchase_batch_id)
             WHERE b.sumber_berat = 'menunggu')
    """)


def downgrade() -> None:
    # Baris yang beratnya NULL tak bisa kembali ke NOT NULL tanpa mengarang
    # angka; CHECK berat_positif menolak 0. Kolomnya dibiarkan boleh NULL.
    op.drop_column("pk_gudang2_intakes", "bobot_final")
    op.drop_column("milling_process", "bobot_masuk_final")
    for tabel in ("purchase_batches", "pk_purchase_batches"):
        op.drop_column(tabel, "berat_perkiraan_kg")
