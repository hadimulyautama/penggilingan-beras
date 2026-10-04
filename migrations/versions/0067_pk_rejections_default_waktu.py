"""`pk_rejections` tak punya DEFAULT basis data untuk created_at/updated_at.

Temuan 4 Oktober 2026, ditemukan menulis baris PERTAMA ke tabel ini sejak
ia lahir (migrasi 0012, 5 Juli 2026) — `create_pk_rejection_dari_timbang`,
pemakai pertamanya. INSERT gagal NOT NULL, bukan diam-diam salah.

Akarnya dua migrasi yang masing-masing benar sendiri tapi berselisih di
sini: 0012 membuat kolomnya TANPA `server_default`, dan 0043 (temuan QA
X-19, "menegakkan apa yang sudah dijanjikan model") menambahkan `SET NOT
NULL` atas premis "semuanya punya server_default" — premis yang salah
justru untuk tabel yang belum pernah ditulis, sehingga tak pernah
ketahuan. Modelnya (`TimestampMixin`) sudah benar sejak awal: `nullable=
False, server_default=func.now()`. Basis datanya yang tertinggal separuh.

Revision ID: 0067_pk_rejections_default_waktu
Revises: 0066_tanda_jasa_tiket
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0067_pk_rejections_default_waktu"
down_revision: Union[str, None] = "0066_tanda_jasa_tiket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE pk_rejections ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE pk_rejections ALTER COLUMN updated_at SET DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE pk_rejections ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE pk_rejections ALTER COLUMN updated_at DROP DEFAULT")
