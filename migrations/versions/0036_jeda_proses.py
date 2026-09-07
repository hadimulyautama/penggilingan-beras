"""Pengeringan dan penggilingan bisa dihentikan sementara, berikut sebabnya.

Mesin berhenti di tengah jalan adalah kejadian sehari-hari — listrik padam,
bahan bakar habis, mesin pendukung rusak, limbah produksi penuh, jam kerja
habis. Sebelum ini aplikasi tak punya tempat untuk itu, dan akibatnya dua:

  · **Jamnya berbohong.** Pengeringan yang tercatat 9 jam padahal 4 jam di
    antaranya mesinnya mati bukan pengeringan 9 jam. Selama waktu berhenti
    tak dipisahkan, tak ada satu pun angka lama-proses yang bisa dipakai
    membandingkan muatan.

  · **Sebabnya hilang.** Yang ditanyakan saat hasil sehari sedikit selalu
    "kenapa", dan sebab yang tak dicatat akan dikarang saat ditanya
    berminggu-minggu kemudian.

Disimpan sebagai TABEL TERSENDIRI, bukan kolom pada lot: satu proses bisa
berhenti berkali-kali, dan yang berguna justru jumlah per sebab — "mesin
pendukung memakan dua jam sehari" adalah belanja, bukan keluhan. Kolom pada
lot hanya bisa menyimpan yang terakhir.

Baris yang `selesai`-nya kosong berarti prosesnya SEDANG berhenti sekarang.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_jeda_proses"
down_revision: Union[str, None] = "0035_mode_dryer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jeda_proses",
        sa.Column("id", sa.Integer, primary_key=True),
        # 'pengeringan' | 'giling' — disimpan meski sudah tersirat dari kolom
        # mana yang terisi, supaya laporan bisa mengelompokkan tanpa menebak.
        sa.Column("jenis", sa.String(20), nullable=False),
        sa.Column("drying_lot_id", sa.Integer,
                  sa.ForeignKey("drying_lots.id"), nullable=True, index=True),
        sa.Column("milling_process_id", sa.Integer,
                  sa.ForeignKey("milling_process.id"), nullable=True, index=True),
        sa.Column("sebab", sa.String(120), nullable=False),
        sa.Column("mulai", sa.DateTime(timezone=True), nullable=False),
        # Kosong = masih berhenti sekarang.
        sa.Column("selesai", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dicatat_oleh", sa.Integer,
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jeda_proses_mulai", "jeda_proses", ["mulai"])


def downgrade() -> None:
    op.drop_index("ix_jeda_proses_mulai", table_name="jeda_proses")
    op.drop_table("jeda_proses")
