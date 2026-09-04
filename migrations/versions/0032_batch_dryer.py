"""Gabah yang menunggu di dryer tahu menunggu di dryer MANA.

Keputusan Direksi 3 September 2026: tiap dryer berjalan sendiri-sendiri —
masing-masing punya giliran dan lotnya sendiri, dan dua lot boleh mengering
bersamaan di dua mesin.

Sampai sekarang "di dryer" adalah satu keadaan tunggal: `status_batch =
'di_dryer'`, tanpa menyebut mesinnya, karena memang hanya ada satu. Dengan
lebih dari satu mesin, keadaan itu tidak lagi cukup — dan tanpa kolom ini,
"mulai pengeringan" akan menyapu gabah dari SEMUA mesin ke dalam satu lot.

Kolomnya sengaja boleh kosong dan hanya berarti pada satu keadaan singkat:
sejak gabah masuk mesin sampai lotnya terbentuk. Setelah itu yang menyimpan
mesinnya adalah `drying_lots.dryer_id`, dan kolom ini dikosongkan lagi —
supaya tidak ada dua tempat yang menyebut mesin untuk gabah yang sama.

Revision ID: 0032_batch_dryer
Revises: 0031_isi_giling
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_batch_dryer"
down_revision: Union[str, None] = "0031_isi_giling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_batches", sa.Column("dryer_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_batches_dryer", "purchase_batches", "dryers", ["dryer_id"], ["id"]
    )
    op.create_index("ix_purchase_batches_dryer", "purchase_batches", ["dryer_id"])

    # Batch yang SEDANG menunggu di dryer saat migrasi ini jalan hanya bisa
    # berada di satu mesin — itulah satu-satunya yang ada. Ditunjuk ke sana,
    # supaya keadaan berjalan tidak menggantung tanpa mesin.
    op.execute("""
        UPDATE purchase_batches b
           SET dryer_id = (SELECT d.id FROM dryers d
                             JOIN warehouses w ON w.id = d.warehouse_id
                            WHERE w.nama_gudang LIKE 'Gudang 1%'
                            ORDER BY d.id LIMIT 1)
         WHERE b.status_batch = 'di_dryer'
    """)


def downgrade() -> None:
    op.drop_index("ix_purchase_batches_dryer", table_name="purchase_batches")
    op.drop_constraint("fk_purchase_batches_dryer", "purchase_batches", type_="foreignkey")
    op.drop_column("purchase_batches", "dryer_id")
