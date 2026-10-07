"""Karung jasa koreksi: `jasa_id` → `pelanggan_id` — milik KONTAK, bukan pesanan.

PEMBALIKAN migrasi 0074, sebelum satu baris pun dipakai di produksi (fitur
baru live, belum sempat dipakai). Koreksi pemilik 7 Oktober 2026: *"jalur
masuk karung untuk jasa bukan berdasarkan proses jasa. tetapi berdasarkan
kontak pelanggan"* — *"maksud saya pindah kepemilikan berdasarkan kontak
pelanggan."*

⚠⚠ INI SENGAJA MELAWAN ATURAN YANG DITULIS DI MANA-MANA UNTUK SEBELAS TABEL
LAIN — `app/services/jasa.py` & CLAUDE.md berulang kali menegaskan
*"pembandingnya `jasa_id`, bukan `pelanggan_id`: dua pesanan satu pelanggan
tetap terpisah, bobot kembalinya berbeda"*. Aturan itu BENAR untuk gabah, PK,
beras, broken, bekatul — barang FISIK yang harus kembali ke pemiliknya
masing-masing, pesanan demi pesanan, sebab dua pesanan bisa punya mutu/berat
berbeda yang tak boleh tercampur.

Karung BUKAN barang yang "dikembalikan" — tak ada "sisa karung pesanan A"
yang harus dibedakan dari "sisa karung pesanan B" milik pelanggan yang sama.
Yang dilacak di sini murni ALOKASI/BIAYA administratif: "berapa karung yang
sudah dianggap jatah pelanggan ini", dan itu pertanyaan tentang KONTAK,
bukan tentang satu pesanan tertentu — pelanggan yang datang berulang
(`Jasa` baru tiap kedatangan, lihat docstring model `Jasa`) tetap SATU
rekening karung, bukan terpecah ulang tiap kedatangan.

`packaging_purchases.pelanggan_id` DAN `packaging_losses.pelanggan_id`
menggantikan `jasa_id` di kedua tabel — pola index sama (parsial,
`pelanggan_id IS NOT NULL`).

Revision ID: 0075_karung_pelanggan
Revises: 0074_karung_jasa
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0075_karung_pelanggan"
down_revision: Union[str, None] = "0074_karung_jasa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABEL_KARUNG = ("packaging_purchases", "packaging_losses")


def upgrade() -> None:
    for tabel in TABEL_KARUNG:
        op.drop_index(f"ix_{tabel}_jasa", table_name=tabel)
        op.drop_column(tabel, "jasa_id")
        op.add_column(tabel, sa.Column(
            "pelanggan_id", sa.Integer(), sa.ForeignKey("pelanggan.id"), nullable=True))
        op.create_index(
            f"ix_{tabel}_pelanggan", tabel, ["pelanggan_id"],
            postgresql_where=sa.text("pelanggan_id IS NOT NULL"),
            sqlite_where=sa.text("pelanggan_id IS NOT NULL"))


def downgrade() -> None:
    for tabel in TABEL_KARUNG:
        op.drop_index(f"ix_{tabel}_pelanggan", table_name=tabel)
        op.drop_column(tabel, "pelanggan_id")
        op.add_column(tabel, sa.Column(
            "jasa_id", sa.Integer(), sa.ForeignKey("jasa.id"), nullable=True))
        op.create_index(
            f"ix_{tabel}_jasa", tabel, ["jasa_id"],
            postgresql_where=sa.text("jasa_id IS NOT NULL"),
            sqlite_where=sa.text("jasa_id IS NOT NULL"))
