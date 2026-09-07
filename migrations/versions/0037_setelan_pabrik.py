"""Setelan yang memang berubah di lapangan, disimpan di basis data.

Sebelum ini setelan hidup di variabel lingkungan: mengubah target kadar air
bawaan berarti menyentuh Railway dan menunggu layanan hidup lagi. Untuk angka
yang ditentukan Direksi sekali setahun itu wajar; untuk angka yang berubah
mengikuti pembeli, tidak.

Dua yang pindah ke sini, dan keduanya dipilih karena sama-sama BERUBAH DI
LAPANGAN — bukan karena kebetulan berupa angka:

  · **target kadar air bawaan** — hanya nilai awal borang; yang menentukan
    tetap operator saat menyalakan mesin, dan ia wajib mengisinya;

  · **sebab berhenti** — inilah yang paling sering perlu ditambah. Kotak
    "Lainnya, tulis sendiri" di borang jeda adalah katupnya, dan sebab yang
    berulang muncul di situ memang layak naik jadi pilihan tetap.

Bentuknya kunci–nilai, bukan satu kolom per setelan: setelan bertambah lebih
sering daripada migrasi ditulis, dan tabel yang butuh migrasi tiap kali
setelan bertambah akan berhenti dipakai.

Batas 48 jam SENGAJA tidak ikut ke sini. Batas yang bisa dilonggarkan oleh
orang yang ingin melonggarkannya bukan batas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_setelan_pabrik"
down_revision: Union[str, None] = "0036_jeda_proses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "setelan_pabrik",
        sa.Column("kunci", sa.String(64), primary_key=True),
        sa.Column("nilai", sa.Text, nullable=False),
        sa.Column("diubah_oleh", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("setelan_pabrik")
