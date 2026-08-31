"""Tautkan intake produksi ke transaksi timbang (aplikasi terpisah, DB terintegrasi).

purchase_batches & pk_purchase_batches menaut ke SATU transaksi timbang lewat
`timbangan_transaksi_id` (UNIQUE → 1 tiket timbang = maksimal 1 batch, cegah dobel).
`sumber_berat` menandai basis bobot batch:
  'nota'      → berat dari nota/surat jalan (timbangan.berat_acuan_kg)
  'timbangan' → berat real hasil timbang (timbangan.netto_timbangan_kg)
  'manual'    → tanpa jembatan timbang (entry lama / pengecualian)

Additif & nullable: baris lama tetap 'manual', tak ada perubahan data/perilaku.
HPP: pakai bobot NOTA bila ada, selain itu bobot real — logika di lapisan aplikasi.

Revision ID: 0027_intake_timbangan_link
Revises: 0026_timbangan_hapus_pengawas
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_intake_timbangan_link"
down_revision: Union[str, None] = "0026_timbangan_hapus_pengawas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("purchase_batches", "pk_purchase_batches")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("timbangan_transaksi_id", sa.Integer(), nullable=True))
        op.add_column(t, sa.Column("sumber_berat", sa.String(length=12),
                                   nullable=False, server_default="manual"))
        op.create_foreign_key(f"fk_{t}_timbangan", t, "timbangan_transaksi",
                              ["timbangan_transaksi_id"], ["id"])
        op.create_unique_constraint(f"uq_{t}_timbangan", t, ["timbangan_transaksi_id"])


def downgrade() -> None:
    for t in _TABLES:
        op.drop_constraint(f"uq_{t}_timbangan", t, type_="unique")
        op.drop_constraint(f"fk_{t}_timbangan", t, type_="foreignkey")
        op.drop_column(t, "sumber_berat")
        op.drop_column(t, "timbangan_transaksi_id")
