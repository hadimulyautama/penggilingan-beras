"""Cermin bertanda, bukan dihapus — Tahap 3, sesudah lima aksi pindah.

Empat tabel cermin mendapat `dibatalkan_pada` (timestamptz, kosong = hidup):
`purchase_batches`, `pk_purchase_batches`, `pk_gudang2_intakes`,
`pk_tumpukan_to_silo` (`internal_transfers` sudah punya `status`).
Pembatalan kini MENANDAI baris, dan pembaca menyaringnya (ORM: saringan
sesi di `app/models/cermin.py`; SQL mentah: eksplisit).

Constraint unik tiket timbang (`uq_purchase_batches_timbangan`,
`uq_pk_purchase_batches_timbangan`) diganti indeks unik PARSIAL yang hanya
menghitung baris hidup, supaya tiket yang pencatatannya dibatalkan bisa
dicatat lagi — nama barunya tetap berawalan `uq_<tabel>_timbangan`, yang
dikenali `_pesan_integritas`. Dua indeks parsial `uq_pk_gudang2_intakes_*`
dibangun ulang dengan syarat yang sama. Tak ada baris yang diubah.

Revision ID: 0052_cermin_bertanda
Revises: 0051_peristiwa_pindah_tumpukan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052_cermin_bertanda"
down_revision: Union[str, None] = "0051_peristiwa_pindah_tumpukan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABEL = ("purchase_batches", "pk_purchase_batches", "pk_gudang2_intakes", "pk_tumpukan_to_silo")


def upgrade() -> None:
    for t in TABEL:
        op.add_column(t, sa.Column("dibatalkan_pada", sa.DateTime(timezone=True), nullable=True))
    for t in ("purchase_batches", "pk_purchase_batches"):
        op.drop_constraint(f"uq_{t}_timbangan", t, type_="unique")
        op.create_index(f"uq_{t}_timbangan_hidup", t, ["timbangan_transaksi_id"], unique=True,
                        postgresql_where=sa.text("dibatalkan_pada IS NULL"))
    op.drop_index("uq_pk_gudang2_intakes_batch", table_name="pk_gudang2_intakes")
    op.create_index("uq_pk_gudang2_intakes_batch", "pk_gudang2_intakes", ["pk_purchase_batch_id"],
                    unique=True,
                    postgresql_where=sa.text("pk_purchase_batch_id IS NOT NULL AND dibatalkan_pada IS NULL"))
    op.drop_index("uq_pk_gudang2_intakes_transfer", table_name="pk_gudang2_intakes")
    op.create_index("uq_pk_gudang2_intakes_transfer", "pk_gudang2_intakes", ["internal_transfer_id"],
                    unique=True,
                    postgresql_where=sa.text("internal_transfer_id IS NOT NULL AND dibatalkan_pada IS NULL"))


def downgrade() -> None:
    # Baris bertanda akan melanggar constraint unik lama: hapus dulu, karena
    # buku besar peristiwa sudah menyimpannya.
    for t in TABEL:
        op.execute(f"DELETE FROM {t} WHERE dibatalkan_pada IS NOT NULL")
    op.drop_index("uq_pk_gudang2_intakes_transfer", table_name="pk_gudang2_intakes")
    op.create_index("uq_pk_gudang2_intakes_transfer", "pk_gudang2_intakes", ["internal_transfer_id"],
                    unique=True, postgresql_where=sa.text("internal_transfer_id IS NOT NULL"))
    op.drop_index("uq_pk_gudang2_intakes_batch", table_name="pk_gudang2_intakes")
    op.create_index("uq_pk_gudang2_intakes_batch", "pk_gudang2_intakes", ["pk_purchase_batch_id"],
                    unique=True, postgresql_where=sa.text("pk_purchase_batch_id IS NOT NULL"))
    for t in ("purchase_batches", "pk_purchase_batches"):
        op.drop_index(f"uq_{t}_timbangan_hidup", table_name=t)
        op.create_unique_constraint(f"uq_{t}_timbangan", t, ["timbangan_transaksi_id"])
    for t in TABEL:
        op.drop_column(t, "dibatalkan_pada")
