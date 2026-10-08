"""PK Gudang 2 bisa keluar — `outgoing_items.silo_id` + jenis barang `pk_g2`.

Pesan kerja 7 Oktober 2026, butir 4 (rinci PESAN-KERJA-11 bagian "LUBANG
KEDUA"): PK titipan pelanggan yang sudah berdiri di silo/tumpukan Gudang 2
tak punya jalan keluar sama sekali — pesanan jasa yang berhenti di tahap ini
tak bisa pernah ditutup.

`silo_id` menunjuk TEMPAT asal PK ini diambil, sama pola dengan
`pk_gudang2_intakes.silo_id` (migrasi 0057): NULL berarti TUMPUKAN, bukan
"tak diisi" — tumpukan sengaja tak punya id sendiri. Kolom ini HANYA berarti
untuk `item_type="pk_g2"`; baris jenis lain selalu menyimpan NULL di sini,
sama seperti `milling_process_id` yang hanya berarti untuk `pk_langsung`.

⚠ Indeksnya BUKAN parsial (`WHERE silo_id IS NOT NULL`) seperti kolom
`jasa_id` di migrasi lain — di sini NULL ADALAH nilai yang dicari
(`hitung_stok_tumpukan`'s suku keluar menyaring `silo_id IS NULL AND
item_type='pk_g2'`), jadi indeks parsial yang membuang baris NULL akan
membuang justru baris yang paling sering dijumlah.

Revision ID: 0076_pk_g2_keluar
Revises: 0075_karung_pelanggan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0076_pk_g2_keluar"
down_revision: Union[str, None] = "0075_karung_pelanggan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outgoing_items", sa.Column(
        "silo_id", sa.Integer(), sa.ForeignKey("silos.id"), nullable=True))
    op.create_index("ix_outgoing_items_silo", "outgoing_items", ["silo_id"])


def downgrade() -> None:
    op.drop_index("ix_outgoing_items_silo", table_name="outgoing_items")
    op.drop_column("outgoing_items", "silo_id")
