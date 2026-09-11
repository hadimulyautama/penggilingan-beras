"""Jejak audit menyimpan MAKSUD aksinya, dan tak lagi dihapus saat dibatalkan.

Temuan QA P-K-02 & P-K-21, 11 September 2026.

`aksi` — pembatalan dulu MENEBAK maksud sebuah catatan dari nama tabel, aksi,
dan nama kolomnya. Tebakan itu salah pada kasus yang paling mudah keliru:
"ubah target kadar air" dan "gabungkan batch ke lot" sama-sama UPDATE pada
`drying_lots`, jadi keduanya jatuh ke penangan yang sama. Membatalkan
perubahan target justru MENGELUARKAN gabah dari lot yang sedang dikeringkan,
dan targetnya sendiri tak kembali. Pratinjaunya berkata "lot pengeringan ·
13.0"; yang terjadi sama sekali lain.

`dibatalkan_pada` / `dibatalkan_oleh` — pembatalan dulu MENGHAPUS baris jejak
auditnya, melanggar ARSITEKTUR §6. Jejak audit bersifat tambah-saja: ia
satu-satunya catatan siapa mengerjakan apa, dan menghapusnya membuang bukti
persis pada saat bukti itu dicari. Sekarang ditandai — dan penanda itu pula
yang mencegah pembatalan ganda, tugas yang dulu dipikul penghapusan.

Ketiganya boleh kosong dan tak ada data lama yang disentuh: baris lama tanpa
tag jatuh ke tebakan lama, yang tetap dipertahankan untuk mereka.

Revision ID: 0039_jejak_undo
Revises: 0038_kode_urut
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_jejak_undo"
down_revision: Union[str, None] = "0038_kode_urut"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("activity_logs", sa.Column("aksi", sa.String(length=40), nullable=True))
    op.create_index("ix_activity_logs_aksi", "activity_logs", ["aksi"])
    op.add_column("activity_logs",
                  sa.Column("dibatalkan_pada", sa.DateTime(timezone=True), nullable=True))
    op.add_column("activity_logs",
                  sa.Column("dibatalkan_oleh", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_activity_logs_dibatalkan_oleh", "activity_logs", "users",
                          ["dibatalkan_oleh"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_activity_logs_dibatalkan_oleh", "activity_logs",
                       type_="foreignkey")
    op.drop_column("activity_logs", "dibatalkan_oleh")
    op.drop_column("activity_logs", "dibatalkan_pada")
    op.drop_index("ix_activity_logs_aksi", table_name="activity_logs")
    op.drop_column("activity_logs", "aksi")
