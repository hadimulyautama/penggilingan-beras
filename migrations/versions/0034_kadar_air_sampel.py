"""Kadar air dicatat dari EMPAT sampel alat tes, bukan satu angka.

Cara mengukurnya di pabrik: operator mengambil empat titik dengan alat tes
kadar air, dan yang dipakai adalah RATA-RATANYA — satu titik saja bisa
kebetulan mengenai bagian yang paling basah atau paling kering. Di samping itu
ada angka yang terbaca pada mesin dryer sendiri.

Tabelnya sudah membedakan `kadar_air_indikator` (bacaan mesin) dari
`kadar_air_tes_manual` (alat tes) sejak awal — yang belum ada adalah empat
sampelnya. Empat kolom ini menyimpan angka MENTAHnya; `kadar_air_tes_manual`
tetap menjadi rata-ratanya, jadi setiap pembaca lama terus bekerja tanpa
disentuh.

Menyimpan yang mentah penting: rata-rata tidak bisa dibongkar kembali, dan
sebaran keempat angka itulah yang memberi tahu apakah gabahnya kering merata
atau baru bagian atasnya.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_kadar_air_sampel"
down_revision: Union[str, None] = "0033_buang_tabel_pk_mati"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KOLOM = ("kadar_air_tes_1", "kadar_air_tes_2", "kadar_air_tes_3", "kadar_air_tes_4")


def upgrade() -> None:
    for nama in _KOLOM:
        op.add_column("drying_moisture_logs",
                      sa.Column(nama, sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    for nama in _KOLOM:
        op.drop_column("drying_moisture_logs", nama)
