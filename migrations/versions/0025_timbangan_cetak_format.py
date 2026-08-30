"""Modul Timbangan: catat format lembar pada riwayat cetak.

Sejak ada dua ukuran bukti (struk 80 mm dan lembar setengah NCR 215×165 mm),
riwayat cetak perlu menyebut yang mana — supaya bila kelak ada sengketa,
tercatat lembar bentuk apa yang benar-benar diterima pengirim.

Baris lama diisi 80MM karena hanya format itu yang pernah ada.

Revision ID: 0025_timbangan_cetak_format
Revises: 0024_timbangan_aturan_cetak
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_timbangan_cetak_format"
down_revision: Union[str, None] = "0024_timbangan_aturan_cetak"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "timbangan_cetak",
        sa.Column("format", sa.String(10), nullable=False, server_default="80MM"),
    )


def downgrade() -> None:
    op.drop_column("timbangan_cetak", "format")
