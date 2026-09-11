"""Indeks pada kolom yang dipakai menyambung dan menyaring paling sering.

Temuan QA P-S-09, 11 September 2026.

Tabel-tabel di bawah selalu ditanya dengan pola "semua baris milik proses
giling nomor sekian", dan tak satu pun punya indeks pada kolom itu. Selama
datanya ratusan baris, Postgres membaca seluruh tabel dan tak ada yang
merasakan apa pun. Itu berhenti diam-diam: biayanya naik seiring tabelnya
tumbuh, dan tabel-tabel inilah yang tumbuh paling cepat — satu baris tiap
kali operator mencatat sesuatu.

`activity_logs.waktu_perubahan` perkaranya sedikit berbeda: layar List audit
menyaring "48 jam terakhir" lalu mengurut terbaru dulu, dan tanpa indeks itu
berarti membaca dan mengurut SELURUH riwayat pencatatan pabrik setiap kali
halamannya dibuka.

Semuanya `IF NOT EXISTS`: sebagian nama mungkin sudah dibuat tangan di server,
dan migrasi yang gagal karena indeks yang sudah ada akan menahan deploy
berikutnya tanpa alasan yang berarti.

Tak ada kolom yang ditambah, tak ada data yang berubah, dan tak satu pun tabel
milik timbangan atau kantor disentuh.

Revision ID: 0042_indeks_panas
Revises: 0041_versi_token_sesi
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0042_indeks_panas"
down_revision: Union[str, None] = "0041_versi_token_sesi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (nama indeks, tabel, kolom) — kolom boleh gabungan, ditulis apa adanya.
INDEKS = [
    # Dibaca tiap kali stok PK, Beranda, atau laporan giling dibuka; selalu
    # "progres terakhir proses ini", jadi urutan waktunya ikut diindeks.
    ("ix_milling_progress_proses", "milling_progress_logs",
     "milling_process_id, waktu_update DESC"),
    ("ix_milling_qc_proses", "milling_qc_logs", "milling_process_id"),
    # "Berapa yang sudah dikirim dari proses ini" — dipakai tiap perhitungan
    # stok PK, dan disaring status.
    ("ix_internal_transfers_proses", "internal_transfers",
     "milling_process_id, status"),
    ("ix_pk_gudang2_intakes_waktu", "pk_gudang2_intakes", "tanggal_masuk"),
    ("ix_pk_gudang2_intakes_silo", "pk_gudang2_intakes", "silo_id"),
    ("ix_silo_storage_silo_status", "silo_storage", "silo_id, status"),
    ("ix_silo_storage_lot", "silo_storage", "drying_lot_id"),
    # List audit: saring rentang waktu, urut terbaru dulu.
    ("ix_activity_logs_waktu", "activity_logs", "waktu_perubahan DESC"),
    ("ix_polishing_silo_usage_proses", "polishing_silo_usage",
     "polishing_process_id"),
    ("ix_drying_moisture_lot", "drying_moisture_logs",
     "drying_lot_id, waktu_update DESC"),
]


def upgrade() -> None:
    for nama, tabel, kolom in INDEKS:
        op.execute(f"CREATE INDEX IF NOT EXISTS {nama} ON {tabel} ({kolom})")


def downgrade() -> None:
    for nama, _tabel, _kolom in INDEKS:
        op.execute(f"DROP INDEX IF EXISTS {nama}")
