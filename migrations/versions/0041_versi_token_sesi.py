"""Akun punya versi token sesi, supaya sesi yang beredar bisa ditarik kembali.

Temuan QA P-S-05, 11 September 2026.

Token sesi bertanda tangan HMAC dan tidak tercatat di mana pun. Yang tersimpan
di dalamnya hanya nomor akun dan waktu kedaluwarsa, jadi sekali ia beredar,
tak ada satu tindakan pun yang bisa menghentikannya sebelum waktunya habis:

  · "Keluar" hanya menghapus cookie di perangkat yang menekannya. HP yang
    hilang tetap masuk sampai 30 hari;
  · mengganti atau mereset sandi tak memutus sesi yang sudah berjalan, jadi
    sandi yang sudah dicuri tetap berguna sesudah diganti;
  · menonaktifkan orang tak memutus apa pun sampai tokennya kedaluwarsa
    sendiri.

Kolom ini ikut di dalam token. Menaikkannya membuat semua token lama berhenti
berlaku seketika.

Nilai awal 1 untuk semua baris, dan token lama yang belum membawa nomor versi
dianggap versi 1 juga. Dengan begitu deploy ini TIDAK memutus siapa pun yang
sedang bekerja; yang terputus hanya mereka yang versinya memang dinaikkan
sesudahnya.

Revision ID: 0041_versi_token_sesi
Revises: 0040_constraint_fisik
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_versi_token_sesi"
down_revision: Union[str, None] = "0040_constraint_fisik"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "produksi_akun",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("produksi_akun", "token_version")
