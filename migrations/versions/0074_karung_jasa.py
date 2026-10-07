"""Karung (kemasan) jadi punya pemilik — `jasa_id` di dua tabel.

Keputusan pemilik 7 Oktober 2026: *"stok karung jasa"* bukan sekadar laporan
pemakaian — stok karung kemasan harus terpisah betul per pemilik, mengubah
keputusan lama di `packaging.py` ("karung jasa memang dari stok kemasan
PABRIK").

Beda dari lima tabel di migrasi 0065: di sana `jasa_id` menandai barang
TITIPAN yang datang dari tiket timbang. Karung tidak punya tiket — pembelian
kemasan (`beli_kemasan()`) TETAP selalu menulis `jasa_id=NULL` (pabrik),
tak berubah oleh migrasi ini. Kolom di `packaging_purchases` di sini dipakai
fitur BARU "Pindah kepemilikan karung" (meniru "Pindah kepemilikan produk
jasa"): memindahkan SEBAGIAN baris pembelian yang sudah ada dari pabrik ke
satu pesanan jasa, lewat pemecahan baris FIFO — bukan ditulis langsung saat
beli.

`packaging_losses` ikut diberi kolom yang sama untuk SIMETRI rumus
(`hitung_stok_kemasan`'s suku `hilang` butuh kolom ini supaya saringan
`jasa_id` bisa menempel di ketiga suku) — bukan karena ada jalur tulis baru.
Tabel ini tak punya satu pun baris tertulis hari ini (`PackagingLoss(` tak
pernah dipanggil di kode); menambah borang pencatatannya di luar permintaan
pekerjaan ini.

Revision ID: 0074_karung_jasa
Revises: 0073_bekatul_bukan_ditahan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0074_karung_jasa"
down_revision: Union[str, None] = "0073_bekatul_bukan_ditahan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABEL_KARUNG = ("packaging_purchases", "packaging_losses")


def upgrade() -> None:
    for tabel in TABEL_KARUNG:
        op.add_column(tabel, sa.Column(
            "jasa_id", sa.Integer(), sa.ForeignKey("jasa.id"), nullable=True))
        op.create_index(
            f"ix_{tabel}_jasa", tabel, ["jasa_id"],
            postgresql_where=sa.text("jasa_id IS NOT NULL"),
            sqlite_where=sa.text("jasa_id IS NOT NULL"))


def downgrade() -> None:
    for tabel in TABEL_KARUNG:
        op.drop_index(f"ix_{tabel}_jasa", table_name=tabel)
        op.drop_column(tabel, "jasa_id")
