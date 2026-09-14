"""Gudang milik catatan, bukan milik orang — temuan QA P4-02.

`activity_logs.gudang` ('g1' / 'g2' / NULL): gudang tempat sebuah catatan
dibuat, diisi pencatat dari tabel yang dicatat. Cakupan pembatalan "operator
Gudang 1/2" kini membaca kolom ini, bukan `users.default_warehouse_id` —
yang sejak operator boleh berpindah gudang mengubah makna riwayat secara
surut.

Baris lama TIDAK diisi. Menebak gudangnya dari profil pencatat hari ini
adalah persis kesalahan yang ditutup migrasi ini; ia masuk kategori "tak
diketahui" dan tak pernah tersapu cakupan gudang mana pun. Akibatnya nyata
tetapi kecil: cakupan gudang hanya melihat catatan sejak migrasi ini
berjalan, dan pembatalan memang cuma menjangkau 48 jam ke belakang.

Revision ID: 0053_activity_logs_gudang
Revises: 0052_cermin_bertanda
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_activity_logs_gudang"
down_revision: Union[str, None] = "0052_cermin_bertanda"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("activity_logs", sa.Column("gudang", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("activity_logs", "gudang")
