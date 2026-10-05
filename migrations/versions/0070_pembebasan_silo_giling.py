"""Pembebasan silo per-silo di Gudang 1 — `berat_akhir_kg`/`berat_terpakai_kg`
pada `milling_process_sources`.

Sebangun dengan `polishing_silo_usage` di Gudang 2: `berat_akhir_kg` NULL
berarti sumber ini masih TERIKAT (silonya masih dianggap sedang digiling);
terisi berarti sudah DIBEBASKAN, dengan sisa yang tercatat saat itu.
`berat_terpakai_kg` = bagian yang benar-benar masuk mesin.

Keputusan pemilik 5 Oktober 2026. Lihat `gudang1.services.milling.
tutup_silo_giling` untuk aturan lengkapnya — termasuk kenapa kolom ini
berdiri di `milling_process_sources` (per BARIS SUMBER, bukan per silo):
satu silo di Gudang 1 bisa punya BANYAK baris sumber (tiap pengisian
melahirkan baris baru, beda dari Gudang 2 yang satu baris per silo), dan
membebaskan satu silo berarti menutup SELURUH baris sumbernya sekaligus.

Revision ID: 0070_pembebasan_silo_giling
Revises: 0069_qc_gabah_merang
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0070_pembebasan_silo_giling"
down_revision: Union[str, None] = "0069_qc_gabah_merang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "milling_process_sources",
        sa.Column("berat_akhir_kg", sa.Numeric(12, 3)),
    )
    op.add_column(
        "milling_process_sources",
        sa.Column("berat_terpakai_kg", sa.Numeric(12, 3)),
    )


def downgrade() -> None:
    op.drop_column("milling_process_sources", "berat_terpakai_kg")
    op.drop_column("milling_process_sources", "berat_akhir_kg")
