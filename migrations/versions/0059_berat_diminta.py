"""Berapa yang DIMINTA ikut tercatat — supaya Admin berhenti menebak.

Temuan QA 28 September 2026: rantai permintaan PK sudah empat langkah dan
rapi, tetapi langkah pertama tak membawa satu angka pun. Operator Gudang 2
menekan "Minta lot ini", lalu Admin melihat kartu yang cuma menyebut LOT
mana — tanpa berapa. Koordinasinya pindah ke luar aplikasi: Admin bertanya
lewat WhatsApp, atau menebak.

Yang ditebak Admin bukan angka kecil. Ia menetapkan BATAS ATAS muatan
(`berat_setuju_kg`), dan batas yang ditebak terlalu kecil membuat Gudang 2
meminta lagi besok; yang ditebak terlalu besar membuat PK berpindah lebih
banyak daripada yang muat di silonya.

SATU KOLOM, dan ia sengaja TIDAK mengubah apa pun tentang wewenang:
`berat_minta_kg` adalah PERMINTAAN, bukan persetujuan. Yang berlaku tetap
`berat_setuju_kg` milik Admin — sama seperti `berat_kirim_kg` milik Gudang 1
tetap disimpan di sebelah `berat_final_kg` milik Admin. Tiga angka yang
berbeda pemiliknya disimpan bertiga, bukan saling menimpa: selisih yang
ditimpa berhenti jadi pertanyaan.

NULL DIIZINKAN, dan itu bukan kelonggaran: permintaan yang lahir sebelum hari
ini memang tak punya angkanya, dan mengarang nilai untuk baris lama berarti
menulis sejarah yang tak pernah terjadi. Yang baru mewajibkannya di layanan,
bukan di basis data.

Revision ID: 0059_berat_diminta
Revises: 0058_permintaan_pk_empat_langkah
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059_berat_diminta"
down_revision: Union[str, None] = "0058_permintaan_pk_empat_langkah"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("permintaan_pk",
                  sa.Column("berat_minta_kg", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("permintaan_pk", "berat_minta_kg")
