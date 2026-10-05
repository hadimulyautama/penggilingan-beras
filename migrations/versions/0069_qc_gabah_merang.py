"""QC PK luar — tambah `gabah` dan `merang` di `pk_purchase_verifications`.

Keputusan pemilik 5 Oktober 2026: dua elemen mutu baru, dinilai dengan skala
kualitatif yang sama dengan `butir_kuning` (bersih/sedikit/sedang/banyak) —
"sedikit" sendiri BARU ditambahkan ke skala itu pada keputusan yang sama,
dulu cuma tiga titik (bersih, sedang, banyak), melompati satu tingkat.

Revision ID: 0069_qc_gabah_merang
Revises: 0068_hapus_potongan_bobot
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0069_qc_gabah_merang"
down_revision: Union[str, None] = "0068_hapus_potongan_bobot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("gabah", sa.String(10)),
    )
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("merang", sa.String(10)),
    )


def downgrade() -> None:
    op.drop_column("pk_purchase_verifications", "merang")
    op.drop_column("pk_purchase_verifications", "gabah")
