"""Hapus potongan bobot QC — `pk_purchase_verifications.potongan_kg`/
`potongan_alasan`.

Keputusan pemilik 4 Oktober 2026. Diperiksa di basis data produksi sebelum
menulis migrasi ini:

    SELECT count(*), count(potongan_kg), count(potongan_alasan)
      FROM pk_purchase_verifications;
    ->  total 0 · potongan 0 · alasan 0

Tabelnya KOSONG sama sekali — tak ada riwayat yang hilang, tak ada baris
yang perlu ditafsirkan sebelum kolomnya dibuang.

**Akibat yang ikut lenyap, dan ini yang penting:** potongan bobot adalah
SATU-SATUNYA jalan di Pos Produksi yang bisa membuat bobot PK yang masuk
Gudang 2 berbeda dari bobot tiket timbangnya. Sesudah migrasi ini:

    bobot PK masuk Gudang 2  =  bobot tiket timbang, SELALU

Tak ada lagi urutan "QC dulu atau masuk dulu" yang berarti apa-apa untuk
bobot — `log_pk_qc` kini murni mencatat MUTU (kadar air, broken, penyusutan,
butir kuning, catatan), tak pernah menyentuh stok.

**Kalau suatu hari sebuah bobot memang perlu dikoreksi**, tempatnya BUKAN
potongan diam-diam di gudang — tempatnya revisi tiket di Pos Timbang
(`jumlah_revisi`, `terkunci`), tempat yang sudah punya jejak revisi sendiri.
Itu menguatkan pemisahan yang sudah dirancang: timbangan satu-satunya yang
berwenang atas bobot; mutu dicatat terpisah tanpa menyentuh angka. Orang
berikutnya yang menghadapi "PK datang kurang dari nota" akan tergoda
menghidupkan kembali potongan bobot di sini — jalannya ada, tapi di Pos
Timbang, bukan di sini.

Revision ID: 0068_hapus_potongan_bobot
Revises: 0067_pk_rejections_default_waktu
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0068_hapus_potongan_bobot"
down_revision: Union[str, None] = "0067_pk_rejections_default_waktu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("pk_purchase_verifications", "potongan_kg")
    op.drop_column("pk_purchase_verifications", "potongan_alasan")


def downgrade() -> None:
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("potongan_kg", sa.Numeric(12, 2)),
    )
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("potongan_alasan", sa.String(120)),
    )
