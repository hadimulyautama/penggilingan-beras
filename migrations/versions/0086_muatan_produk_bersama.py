"""Rincian produk bersama pada setiap baris muatan timbang.

Kolom nullable menjaga tiket lama dan muatan curah tetap kompatibel.
Migrasi ini dijalankan oleh service app sebagai satu-satunya pemilik migrasi
database bersama; migrasi 0042 pada repo Timbangan adalah cerminnya.

Revision ID: 0086_muatan_produk_bersama
Revises: 0085_mutu_stok_beras_lama
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0086_muatan_produk_bersama"
down_revision: Union[str, None] = "0085_mutu_stok_beras_lama"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


KOLOM = {
    "kualitas_id": sa.Integer(),
    "merek_produk_id": sa.Integer(),
    "packaging_material_id": sa.Integer(),
    "package_size_id": sa.Integer(),
}
FK = {
    "kualitas_id": ("rice_quality_standards", "id"),
    "merek_produk_id": ("brands", "id"),
    "packaging_material_id": ("packaging_materials", "id"),
    "package_size_id": ("package_sizes", "id"),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom_ada = {c["name"] for c in inspector.get_columns("timbangan_muatan")}
    for nama, tipe in KOLOM.items():
        if nama not in kolom_ada:
            op.add_column("timbangan_muatan", sa.Column(nama, tipe, nullable=True))

    fk_ada = {c["name"] for c in inspector.get_foreign_keys("timbangan_muatan")}
    for nama, (tabel, kolom) in FK.items():
        nama_fk = f"fk_timbangan_muatan_{nama}"
        if nama_fk not in fk_ada:
            op.create_foreign_key(nama_fk, "timbangan_muatan", tabel, [nama], [kolom])


def downgrade() -> None:
    # Rincian produk pada tiket adalah data bersama; jangan hapus saat downgrade.
    pass
