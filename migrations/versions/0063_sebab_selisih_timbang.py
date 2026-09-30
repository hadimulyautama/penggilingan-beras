"""Selisih timbang yang BESAR wajib bersebab — dan sebabnya disimpan.

Keputusan pemilik 30 September 2026, atas usul QA. Pertanyaan operator yang
melahirkannya: "apabila ada beras dan broken keluar jadi 1 mobil, bagaimana
cara menimbangnya, karena berat beras dan broken berbeda?"

Jawabannya: jangan membagi angka timbangan. Tiap baris punya angkanya sendiri
dari karung yang dimuat; tiket memberi SATU angka untuk seluruh bak; dan
verifikasi membandingkan TOTAL lawan TOTAL. Selisih kecil wajar — karung tak
persis 25,0 kg, ada palet, ada terpal.

Yang belum ada: apa yang terjadi kalau selisihnya BESAR. Sampai hari ini
angkanya cuma ditampilkan, dan transaksi ditutup sama saja apakah bedanya 20
kg atau 2.000 kg. Pemilik memilih: boleh tetap ditutup — truknya sudah
berangkat berjam-jam sebelumnya dan menahan penutupan tak mengembalikannya —
TETAPI ditandai, dan sebabnya wajib ditulis.

KOLOM SENDIRI, bukan menumpang `catatan`. `catatan` adalah tempat bebas yang
artinya ditentukan siapa pun yang mengisinya; kolom ini punya satu arti
tunggal dan dibaca sebagai TANDA: yang berisi adalah transaksi yang
selisihnya pernah melewati ambang, dan itu pertanyaan yang kelak ditanyakan.
Menumpang kolom bebas berarti tandanya hilang begitu ada orang menulis hal
lain di sana.

NULL pada baris lama, dan tak ditebak: transaksi yang ditutup sebelum hari
ini memang tak pernah ditanyai sebabnya, dan mengarang sebab berarti menulis
keterangan yang tak pernah diberikan siapa pun.

Revision ID: 0063_sebab_selisih_timbang
Revises: 0062_pembeli_dari_kledo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0063_sebab_selisih_timbang"
down_revision: Union[str, None] = "0062_pembeli_dari_kledo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outgoing_records",
                  sa.Column("sebab_selisih", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("outgoing_records", "sebab_selisih")
