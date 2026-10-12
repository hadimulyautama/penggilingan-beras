"""Simpan daftar komoditas yang diizinkan per silo.

Revision ID: 0089_silo_filter_komoditas
Revises: 0088_proses_terpadu
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0089_silo_filter_komoditas"
down_revision: Union[str, None] = "0088_proses_terpadu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("silos", sa.Column("komoditas_diizinkan", sa.JSON(), nullable=True))
    op.execute(sa.text("""
        UPDATE silos
        SET komoditas_diizinkan = '["gabah_kering"]'
        WHERE warehouse_id IN (
            SELECT id FROM warehouses WHERE lower(nama_gudang) LIKE 'gudang 1%'
        )
    """))
    op.execute(sa.text("""
        UPDATE silos
        SET komoditas_diizinkan = '["pk", "beras_putih", "reject", "broken", "menir"]'
        WHERE komoditas_diizinkan IS NULL
    """))


def downgrade() -> None:
    op.drop_column("silos", "komoditas_diizinkan")
