"""`timbangan_transaksi.jasa` — idempoten di sisi produksi (kolomnya milik
rantai repo `timbangan`, lihat migrasi kembarnya `0041_tanda_jasa` di sana).

Cacat lapangan 2 Oktober 2026: "ini tiket jasa?" diturunkan dari
`pelanggan_id IS NOT NULL` (`timbang_link.adalah_jasa`) — dan itu SALAH untuk
pelanggan BARU yang diketik bebas di pintu ketik-bebas: `pelanggan_id`-nya
tetap kosong sampai `purchase.find_or_create_pelanggan` membuatnya DI SINI,
bukan di Pos Timbang. Baris tiket "jasa-pelanggan-baru" jadi identik
bentuknya dengan "pembelian-pemasok-baru", dan `create_purchase_batch_dari_
timbang` membuat PEMASOK PALSU dari nama pelanggan — persis yang dilarang
keras spek D3.

Kolom barunya `jasa` dibaca `timbang_link._SQL_AKTIF`/`_SQL_SATU` dan
`adalah_jasa()` memakainya SEBAGAI PENENTU UTAMA (`pelanggan_id`/`jasa_id`
tetap dibaca sebagai kaki kedua, untuk tiket LAMA sebelum migrasi ini ada).

Di basis data uji repo ini, rantai `timbangan` tak pernah berjalan — pola yang
sama persis dengan `pelanggan_id` di 0064; lihat catatan panjang di sana.

Revision ID: 0066_tanda_jasa_tiket
Revises: 0065_jasa_gudang2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0066_tanda_jasa_tiket"
down_revision: Union[str, None] = "0065_jasa_gudang2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom = {c["name"] for c in inspector.get_columns("timbangan_transaksi")}
    if "jasa" not in kolom:
        op.add_column(
            "timbangan_transaksi",
            sa.Column("jasa", sa.Boolean(), nullable=False,
                     server_default=sa.false()))
        # Baris LAMA: satu-satunya kebenaran yang tersedia untuk riwayat
        # sebelum kolom ini ada. Tiket jasa lama yang pelanggannya diketik
        # bebas TETAP salah tanda (data yang sudah identik dengan pembelian
        # biasa tak bisa dibedakan lagi) — migrasi ini menghentikan kerusakan
        # BARU, bukan membetulkan yang sudah terjadi.
        op.execute(
            "UPDATE timbangan_transaksi SET jasa = true "
            "WHERE pelanggan_id IS NOT NULL OR jasa_id IS NOT NULL"
        )


def downgrade() -> None:
    # TIDAK dijatuhkan sama sekali — sama alasannya dengan `pelanggan_id` di
    # 0064: kolom ini milik rantai repo `timbangan` (lahir di migrasi
    # kembarnya `0041_tanda_jasa` di sana), dan turun dari migrasi INI tak
    # boleh merobohkan Pos Timbang di repo sebelah, yang tak pernah meminta
    # migrasi ini turun.
    pass
