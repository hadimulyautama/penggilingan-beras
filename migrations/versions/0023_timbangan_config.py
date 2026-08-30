"""Modul Timbangan: tabel setelan operasional `timbangan_config`.

Menampung parameter yang boleh diubah Admin dari layar tanpa deploy ulang
(kapasitas jembatan, kelipatan tera, jam kunci, jam tiket menganggur, batas
ukuran foto). Baris yang tidak ada berarti "pakai nilai environment", jadi
tabel yang kosong sama artinya dengan perilaku sebelum migrasi ini.

Revision ID: 0023_timbangan_config
Revises: 0022_timbangan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_timbangan_config"
down_revision: Union[str, None] = "0022_timbangan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timbangan_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kunci", sa.String(40), nullable=False, unique=True),
        sa.Column("nilai", sa.String(120), nullable=False),
        sa.Column(
            "diubah_oleh_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("timbangan_config")
