"""Gudang 2 menurut pemilik: silo yang dipoles boleh diisi, penyosohan bisa berhenti.

Keputusan pemilik 12 September 2026, saat aplikasi operator Gudang 2 (repo
`gudang2/`) dirancang di atas API internal repo ini:

  · **Silo yang sedang dipoles TETAP boleh menerima PK.** Di lapangan silo
    memang diisi lagi sesuai kebutuhan. Sampai sekarang intake ditolak
    (temuan QA P-K-11) supaya rumus bahan terpakai — awal − akhir — tetap
    benar. Sekarang rumusnya yang diubah: terpakai = awal + DITAMBAH − akhir,
    dan yang ditambahkan selama proses dicatat pada pemakaian silonya
    (`polishing_silo_usage.berat_masuk_kg`). Rendemen tetap dihitung atas
    bahan yang sungguh masuk mesin.

  · **Penyosohan bisa berhenti sementara**, seperti pengeringan dan giling.
    `jeda_proses` mendapat kolom ketiga penunjuk proses:
    `polishing_process_id`. Jenisnya "penyosohan".

  · Tumpukan PK Gudang 2 tak lagi berbatas — itu perubahan konfigurasi
    (`G2_TUMPUKAN_MAKS_KG` = 0), bukan skema.

Kolom baru berisi 0 untuk seluruh pemakaian silo yang sudah ada: tidak ada
PK yang pernah masuk selama proses, karena sampai hari ini ia ditolak.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_gudang2_operator"
down_revision: Union[str, None] = "0045_nama_pemasok_unik"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "polishing_silo_usage",
        sa.Column("berat_masuk_kg", sa.Numeric(12, 2), nullable=False,
                  server_default="0"),
    )
    op.add_column(
        "jeda_proses",
        sa.Column("polishing_process_id", sa.Integer,
                  sa.ForeignKey("polishing_process.id"), nullable=True),
    )
    op.create_index("ix_jeda_proses_polishing_process_id", "jeda_proses",
                    ["polishing_process_id"])


def downgrade() -> None:
    op.drop_index("ix_jeda_proses_polishing_process_id", table_name="jeda_proses")
    op.drop_column("jeda_proses", "polishing_process_id")
    op.drop_column("polishing_silo_usage", "berat_masuk_kg")
