"""Nomor kode harian dari penghitung atomik, bukan dari jumlah baris.

Temuan QA P-K-01 (Kritis), 11 September 2026.

Kode harian dibentuk `SELECT count(*) … + 1` atas tabelnya sendiri. Dua hal
salah di situ, dan keduanya sudah terjadi di pabrik:

**Undo menghapus baris.** Sesudah GB-01 dibatalkan, hitungannya kembali nol,
jadi truk berikutnya menghitung GB-02 — yang sudah ada — lalu ditolak indeks
unik. Dan tetap ditolak SEPANJANG HARI, karena tiap percobaan menghitung angka
yang sama. Yang dibaca operator: "Tiket timbang ini sudah ditautkan ke batch
lain" — pesan yang tak menyebut sebabnya sama sekali.

**Dua operator bersamaan** menghitung angka yang sama sebelum salah satunya
menyimpan.

Berlaku untuk SELURUH awalan: GB, PGR, LOT, TRF, PKB, POL, PTS, REJ, OUT, PKP.

NILAI AWAL DIISI DARI KODE YANG SUDAH ADA — nomor tertinggi per awalan &
tanggal, dibaca dari kodenya sendiri, bukan dari jumlah baris. Membaca jumlah
baris akan mengulangi kekeliruan yang sama: baris yang sudah dibatalkan tak
lagi terhitung, dan penghitungnya lahir langsung dengan angka yang bentrok.

Nomor BOLEH MELOMPAT sesudah pembatalan. Itu disengaja: nomor yang muncul dua
kali di buku dan di surat jalan lebih membingungkan daripada nomor yang
bolong.

Tabel `timbangan_*` dan `kantor_*` tidak disentuh.

Revision ID: 0038_kode_urut
Revises: 0037_setelan_pabrik
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_kode_urut"
down_revision: Union[str, None] = "0037_setelan_pabrik"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (tabel, kolom kode) untuk tiap awalan. Awalannya sendiri dibaca dari
#: kodenya, jadi daftar ini tak perlu menyebutkannya lagi — dan tak bisa
#: berselisih dengan `codegen.py` yang tetap jadi otoritasnya.
SUMBER = [
    ("purchase_batches", "kode_batch"),
    ("drying_lots", "kode_lot"),
    ("milling_process", "kode_proses"),
    ("internal_transfers", "kode_transfer"),
    ("pk_purchase_batches", "kode_batch"),
    ("pk_rejections", "kode"),
    ("pk_tumpukan_to_silo", "kode_pindah"),
    ("polishing_process", "kode_proses"),
    ("packaging_purchases", "kode"),
    ("outgoing_records", "kode"),
]


def upgrade() -> None:
    op.create_table(
        "kode_urut",
        sa.Column("awalan", sa.String(length=8), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("awalan", "tanggal"),
    )

    # ── Nilai awal: nomor TERTINGGI yang sudah terpakai, per awalan & tanggal ──
    #
    # Dibaca dari kodenya sendiri (AWALAN-YYYYMMDD-NN), bukan dari jumlah
    # baris. Kode yang bentuknya lain — tiket lama berawalan TRX-, atau apa
    # pun yang tak berpola — dilewati oleh saringan panjang & pola di bawah,
    # bukan ditebak.
    sambung = op.get_bind()
    for tabel, kolom in SUMBER:
        ada = sambung.execute(sa.text(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = :t"
        ), {"t": tabel}).scalar()
        if not ada:
            continue
        sambung.execute(sa.text(f"""
            INSERT INTO kode_urut (awalan, tanggal, n)
            SELECT split_part({kolom}, '-', 1) AS awalan,
                   to_date(split_part({kolom}, '-', 2), 'YYYYMMDD') AS tanggal,
                   max(CAST(split_part({kolom}, '-', 3) AS integer)) AS n
              FROM {tabel}
             WHERE {kolom} ~ '^[A-Z]+-[0-9]{{8}}-[0-9]+$'
             GROUP BY 1, 2
            ON CONFLICT (awalan, tanggal)
            DO UPDATE SET n = greatest(kode_urut.n, EXCLUDED.n)
        """))


def downgrade() -> None:
    op.drop_table("kode_urut")
