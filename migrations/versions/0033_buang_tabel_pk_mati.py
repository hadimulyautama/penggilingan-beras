"""Buang dua tabel PK yang tak pernah terisi.

`pk_stock_gudang1` dan `milling_pk_routing` dibuat di migrasi 0002 dan tidak
pernah ditulis maupun dibaca satu kali pun — tak ada satu rujukan di seluruh
app/. Keduanya selalu kosong di produksi.

Keduanya bukan sekadar sisa: masing-masing memuat satu ATURAN yang saat itu
dimaksudkan tetapi tak pernah dibangun —

  · pk_stock_gudang1  : buffer PK Gudang 1 "maks 30 ton, dipisah per lot"
  · milling_pk_routing: PK diarahkan ke `tumpuk` atau `siap_transfer`

Karena itu keduanya sengaja TIDAK dihapus lebih dulu, sekalipun sudah
ketahuan mati: docstring-nya satu-satunya catatan tertulis bahwa aturan itu
pernah ada. Sekarang keduanya sudah terjawab — dengan cara yang lebih baik,
dan atas keputusan pemilik:

  · Batasnya 80 ton, bukan 30, dan ia BATAS FISIK LANTAI. Ditegakkan sebagai
    peringatan di `log_progress` terhadap `stok_pk_g1()`.
  · "Ditumpuk" vs "siap transfer" tidak perlu dinyatakan siapa pun. Keduanya
    sudah dibedakan oleh sesuatu yang tercatat sendiri: ada tidaknya transfer.
    Hasil giling otomatis menumpuk; yang dicatat hanya pengecualiannya, yaitu
    saat PK dibawa langsung ke Gudang 2.

Menyimpan keadaan yang bisa diturunkan berarti dua sumber untuk satu fakta,
dan yang salah selalu yang diketik manual — orang lupa memperbaruinya setelah
barangnya benar-benar pindah.

`downgrade` membangun keduanya kembali persis seperti di 0002. Isinya tidak
dikembalikan karena memang tak pernah ada.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_buang_tabel_pk_mati"
down_revision: Union[str, None] = "0032_batch_dryer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.drop_table("pk_stock_gudang1")
    op.drop_table("milling_pk_routing")


def downgrade() -> None:
    op.create_table(
        "milling_pk_routing",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("milling_process_id", sa.Integer,
                  sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tujuan", sa.String(20), nullable=False),
        sa.Column("status_transfer", sa.String(20)),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_table(
        "pk_stock_gudang1",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id")),
        sa.Column("milling_process_id", sa.Integer,
                  sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), server_default="0"),
        sa.Column("status", sa.String(20), server_default="tersedia"),
        *_timestamps(),
    )
