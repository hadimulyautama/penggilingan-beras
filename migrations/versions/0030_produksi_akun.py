"""Kredensial masuk webapp produksi (Fase B, tahap B1).

Hanya kredensial. Identitas & peran tetap di `users` — tabel ini menautnya
lewat `user_id` yang UNIQUE, jadi satu orang tepat satu akun. Tidak ada kolom
peran di sini dengan sengaja: peran yang tersalin di dua tempat cepat atau
lambat berbeda, dan tak ada yang tahu mana yang benar.

`mode_perangkat` berbawaan 'bersama' (perangkat gudang) — bawaan yang aman.
Operator memakai perangkat gudang supaya data pabrik tidak menetap di HP
pribadi; admin & staff dinaikkan ke 'pribadi' saat akunnya dibuat.

Revision ID: 0030_produksi_akun
Revises: 0029_pelanggan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_produksi_akun"
down_revision: Union[str, None] = "0029_pelanggan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "produksi_akun",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="aktif", nullable=False),
        sa.Column("mode_perangkat", sa.String(length=10), server_default="bersama", nullable=False),
        sa.Column("harus_ganti_sandi", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("terakhir_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("username"),
    )


def downgrade() -> None:
    op.drop_table("produksi_akun")
