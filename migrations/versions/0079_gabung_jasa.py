"""Pesanan jasa bisa digabung OTOMATIS — pelanggan sama, campur fisik sah.

Keputusan pemilik 10 Oktober 2026, menagih kalimatnya sendiri yang sudah
tertulis di docstring `Jasa` sejak 1 Oktober: *"yang tidak memungkinkan
adalah menggabungkan barang jika KEPEMILIKAN berbeda. itu saja batasannya."*
Kepemilikan berarti PELANGGAN — bukan nomor pesanan administratif
(`jasa_id`). Permintaan konkret: gabah milik Catur di Silo A, dan gabah
Catur lain yang baru selesai dikeringkan, HARUS bisa dicampur ke Silo A
juga — walau keduanya kebetulan dua pesanan (dua kedatangan terpisah,
masing-masing sudah melahirkan `Jasa` sendiri sebelum bertemu di gudang).

Bukan batasan baru yang dicabut, melainkan GRANULARITAS yang dibetulkan:
pagar "tak boleh campur pemilik" (`pastikan_satu_jasa`) TETAP keras — yang
berubah adalah APA YANG DIHITUNG SEBAGAI "pemilik sama" di titik campur
(silo/dryer/proses), lewat `pastikan_satu_pemilik()` (BARU,
`app/services/jasa.py`) yang MENGGABUNGKAN otomatis dua pesanan pelanggan
yang sama saat keduanya bertemu secara fisik — bukan menggabungkan pesanan
yang pelanggannya BERBEDA, itu tetap ditolak sekeras sebelumnya.

Dua kolom baru di `jasa`, pola PERSIS `dibatalkan_pada` yang sudah ada:
`status` yang dibaca layar, kolom `digabung_pada` KAPAN-nya — pembaca
menyaring `status`, bukan kolom ini. `digabung_ke_id` menunjuk pesanan yang
MENYERAP (survivor) — pesanan yang "digabung" bukan dihapus, selaras
"cermin bertanda, bukan dihapus": `nota_jasa()`/`sisa_jasa()` atas pesanan
yang sudah digabung akan menjawab nol (seluruh barisnya sudah dipindah ke
survivor) sejak hari pertama — dibedakan dari SELESAI oleh status yang baru
ini, bukan oleh menebak dari angka nol.

Revision ID: 0079_gabung_jasa
Revises: 0078_beras_ke_silo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0079_gabung_jasa"
down_revision: Union[str, None] = "0078_beras_ke_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jasa", sa.Column("digabung_ke_id", sa.Integer,
                                    sa.ForeignKey("jasa.id"), nullable=True))
    op.add_column("jasa", sa.Column("digabung_pada", sa.DateTime(timezone=True),
                                    nullable=True))
    op.create_index("ix_jasa_digabung_ke_id", "jasa", ["digabung_ke_id"],
                    postgresql_where=sa.text("digabung_ke_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_jasa_digabung_ke_id", table_name="jasa")
    op.drop_column("jasa", "digabung_pada")
    op.drop_column("jasa", "digabung_ke_id")
