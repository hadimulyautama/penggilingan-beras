"""outgoing_items.jasa_id — kepemilikan PER BARIS, bukan hanya per transaksi.

Keputusan pemilik 11 Oktober 2026: "picker 'pesanan jasa' ganti dengan
picker nama pelanggan... barang yang diambil adalah list barang yang
merupakan kepemilikan pelanggan yang kita pilih" — lalu, lebih tegas lagi
sesudah laporan lapangan nyata (Pak Pras punya PK di Gudang 1 DAN Gudang 2,
dua pesanan berbeda yang tak pernah bertemu fisik jadi tak tergabung
otomatis): "filter menurut pesanan hapus saja... sekali kiriman saya mau
kirim semuanya."

Satu PELANGGAN boleh punya beberapa pesanan jasa (`Jasa`) aktif sekaligus
— kedatangan terpisah yang kebetulan belum/tak pernah bertemu fisik di satu
silo/dryer/proses (lihat migrasi 0079, `pastikan_satu_pemilik`). Sampai
migrasi ini, SATU truk pengambilan cuma bisa membawa barang dari SATU
pesanan: `outgoing_records.jasa_id` adalah satu nilai untuk SELURUH
transaksi, dan `sisa_jasa()` membaca "sudah diambil" lewat kolom itu.

Kolom baru ini memindahkan kepemilikan ke tingkat BARIS: tiap
`OutgoingItem` kini tahu sendiri dari pesanan jasa mana ia diambil, lepas
dari pesanan mana yang disebut transaksinya (`outgoing_records.jasa_id`,
yang sejak sekarang NULL kalau transaksinya menggabung lebih dari satu
pesanan — lihat catatan di kolom itu). `sisa_jasa()` dirombak bersamaan
(lihat `app/services/jasa.py`) untuk membaca kolom ini, bukan lagi
`outgoing_records.jasa_id`, demi "sudah diambil"-nya PK Gudang 2 dan
barang jadi.

Backfill AMAN tanpa syarat: sebelum migrasi ini SETIAP transaksi memang
cuma punya satu `jasa_id` (disalin rata ke seluruh barisnya oleh
`buat_perintah`/`tambah_baris` yang lama), jadi menyalinnya ke tiap baris
tidak mengubah satu pun fakta yang sudah tercatat.

Revision ID: 0080_outgoing_item_jasa_id
Revises: 0079_gabung_jasa
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0080_outgoing_item_jasa_id"
down_revision: Union[str, None] = "0079_gabung_jasa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outgoing_items", sa.Column(
        "jasa_id", sa.Integer, sa.ForeignKey("jasa.id"), nullable=True))
    op.create_index(
        "ix_outgoing_items_jasa", "outgoing_items", ["jasa_id"],
        postgresql_where=sa.text("jasa_id IS NOT NULL"))
    # Backfill dari transaksinya — AMAN tanpa syarat, lihat docstring modul.
    op.execute("""
        UPDATE outgoing_items oi
        SET jasa_id = orec.jasa_id
        FROM outgoing_records orec
        WHERE orec.id = oi.outgoing_record_id
          AND orec.jasa_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_outgoing_items_jasa", table_name="outgoing_items")
    op.drop_column("outgoing_items", "jasa_id")
