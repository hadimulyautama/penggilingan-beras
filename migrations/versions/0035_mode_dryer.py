"""Pengeringan menyandang target kadar air & mode mesin yang dipakai.

Dua hal yang ditetapkan operator SEBELUM mesin dinyalakan:

  · **Target kadar air** — sampai berapa gabah ini dikeringkan. Sebelumnya
    hanya ada satu angka umum di setelan aplikasi, padahal targetnya bisa
    berbeda antar muatan: gabah untuk digiling sendiri dan gabah untuk dijual
    tidak selalu dituju ke angka yang sama.

  · **Mode dryer** (15T/20T/25T/30T/35T) — mesin punya beberapa mode menurut
    tonase, dan operator harus menyetelnya di mesin. Yang disimpan di sini
    KONFIRMASI bahwa ia sudah menyetelnya, bukan perintah ke mesin: aplikasi
    ini tidak tersambung ke dryer. Kegunaannya muncul belakangan — muatan yang
    dikeringkan dengan mode yang tak cocok bisa dilacak saat hasilnya
    mengecewakan.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_mode_dryer"
down_revision: Union[str, None] = "0034_kadar_air_sampel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drying_lots",
                  sa.Column("target_kadar_air", sa.Numeric(5, 2), nullable=True))
    op.add_column("drying_lots",
                  sa.Column("mode_dryer", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("drying_lots", "mode_dryer")
    op.drop_column("drying_lots", "target_kadar_air")
