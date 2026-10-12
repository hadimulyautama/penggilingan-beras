"""Tautkan batch gabah dan PK ke identitas Armada bersama.

Kolom nomor polisi lama dipertahankan sebagai snapshot laporan. `armada_id`
menjadi hubungan stabil ke master kendaraan yang sebelumnya dibuat Timbangan.

Revision ID: 0087_armada_bersama
Revises: 0086_muatan_produk_bersama
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0087_armada_bersama"
down_revision: Union[str, None] = "0086_muatan_produk_bersama"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("purchase_batches", "pk_purchase_batches"):
        cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "armada_id" not in cols:
            op.add_column(table, sa.Column("armada_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                f"fk_{table}_armada_id", table, "timbangan_kendaraan",
                ["armada_id"], ["id"],
            )
            op.create_index(f"ix_{table}_armada_id", table, ["armada_id"])

    # Hubungkan catatan lama ke master yang sudah ada tanpa mengubah snapshot
    # nomor polisi. Plat yang belum pernah masuk master dibiarkan tanpa tautan.
    for table in ("purchase_batches", "pk_purchase_batches"):
        op.execute(sa.text(f"""
            UPDATE {table} AS batch
               SET armada_id = armada.id
              FROM timbangan_kendaraan AS armada
             WHERE batch.armada_id IS NULL
               AND batch.no_polisi_truk IS NOT NULL
               AND upper(regexp_replace(trim(batch.no_polisi_truk), '[[:space:]]+', ' ', 'g'))
                   = armada.nomor_polisi
        """))


def downgrade() -> None:
    # Tautan identitas dipertahankan seperti FK lain lintas aplikasi; menghapus
    # kolom akan memutus jejak historis yang telah dibangun.
    pass
