"""`beras_ke_silo` — beras (curah/berkemasan) dipindah jadi bahan baku silo.

Dua pintu sekaligus, keputusan pemilik 8 Oktober 2026:

  1. **Silo Beras** (`silos.jenis_isi='beras'`, nilai KETIGA — sebelumnya
     hanya 'pk'/'broken', migrasi 0071) — beras GRADE (premium/medsuper/
     medium/sayur/beras_b) dicampur di sana, sebangun silo broken.
  2. **Silo A & B** (`jenis_isi='pk'`, TAK BERUBAH) kini JUGA menerima
     `beras_putih` (beras mutu belum ditetapkan) sebagai bahan sosoh ulang —
     bukan silo baru, cuma jalan masuk baru ke silo yang sudah ada.

Sebangun `broken_ke_silo` (migrasi 0072), TAPI sumbernya bukan baris
`byproduct_stock` — beras tak punya tabel curah tersendiri (curah beras
dihitung `keluar_mesin − dikemas`, murni aritmetika, lihat `app.services.
stok.beras_curah`), jadi baris ini menunjuk `polishing_process_id` + `jenis`
langsung, bukan sebuah baris stok. `jenis` WAJIB disimpan di sini (beda dari
broken, yang jenisnya selalu "broken") — satu proses bisa punya beberapa
grade sekaligus, dan `beras_curah()`/`stok_produk()` butuh menyaring per
jenis supaya yang dipindah ke silo tak lagi terbaca "belum dicatat" di sana.

Revision ID: 0078_beras_ke_silo
Revises: 0077_gabah_kering_dikemas
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0078_beras_ke_silo"
down_revision: Union[str, None] = "0077_gabah_kering_dikemas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "beras_ke_silo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_pindah", sa.String(20), nullable=False, unique=True),
        sa.Column("polishing_process_id", sa.Integer,
                  sa.ForeignKey("polishing_process.id"), nullable=False),
        sa.Column("jenis", sa.String(20), nullable=False),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jasa_id", sa.Integer, sa.ForeignKey("jasa.id")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_beras_ke_silo_polishing_process_id", "beras_ke_silo",
                    ["polishing_process_id"])
    op.create_index("ix_beras_ke_silo_silo_id", "beras_ke_silo", ["silo_id"])


def downgrade() -> None:
    op.drop_table("beras_ke_silo")
