"""Basis data menolak keadaan yang mustahil secara fisik.

Temuan QA P-K-04 … P-K-14, 11 September 2026. Tak ada satu pun `FOR UPDATE` di
kode, jadi dua operator yang bekerja bersamaan bisa membuat keadaan yang tak
mungkin ada di gudang:

· PK luar masuk Gudang 2 DUA KALI — 20 dari 20 percobaan.
· Satu lot pengeringan masuk Silo A dan Silo B sekaligus.
· Dua proses giling berjalan di satu silo.
· Satu batch gabah masuk dua lot pengeringan.

Pemeriksaan di kode tak cukup, dan itu bukan soal kurang teliti: ia berlaku
hanya untuk jalur yang memanggilnya. Jalur baru yang lupa memeriksa akan lolos
diam-diam, dan dua permintaan yang datang bersamaan sama-sama lolos karena
keduanya memeriksa sebelum salah satunya menulis. Basis data tak punya celah
itu.

**MEMERIKSA LEBIH DULU, tak menghapus apa pun.** Migrasi yang menambahkan
constraint pada data yang sudah melanggar akan gagal di tengah deploy — atau,
lebih buruk, menggoda orang berikutnya menghapus baris yang menghalangi. Jadi
ia berhenti dengan menyebut baris mana yang bermasalah, dan pemiliknya yang
memutuskan.

Tabel `timbangan_*`, `kantor_*`, dan tabel master milik repo core (suppliers,
silos, dryers) tidak disentuh.

Revision ID: 0040_constraint_fisik
Revises: 0039_jejak_undo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_constraint_fisik"
down_revision: Union[str, None] = "0039_jejak_undo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (nama indeks, tabel, kolom, syarat) — semuanya PARSIAL.
#:
#: Parsial karena yang dilarang bukan nilainya, melainkan nilai itu SELAGI
#: dalam keadaan tertentu. Satu lot boleh pernah berada di Silo A lalu pindah
#: ke Silo B; yang mustahil adalah berada di keduanya SEKALIGUS.
INDEKS = [
    ("uq_pk_gudang2_intakes_batch", "pk_gudang2_intakes",
     "pk_purchase_batch_id", "pk_purchase_batch_id IS NOT NULL"),
    ("uq_pk_gudang2_intakes_transfer", "pk_gudang2_intakes",
     "internal_transfer_id", "internal_transfer_id IS NOT NULL"),
    ("uq_silo_storage_lot_terisi", "silo_storage",
     "drying_lot_id", "drying_lot_id IS NOT NULL AND status = 'terisi'"),
    ("uq_silo_storage_batch_terisi", "silo_storage",
     "purchase_batch_id", "purchase_batch_id IS NOT NULL AND status = 'terisi'"),
    ("uq_drying_lot_batches_batch", "drying_lot_batches",
     "purchase_batch_id", "purchase_batch_id IS NOT NULL"),
    ("uq_milling_process_silo_proses", "milling_process",
     "silo_id", "silo_id IS NOT NULL AND status = 'proses'"),
]

#: Tabel pergerakan barang yang beratnya tak mungkin nol atau negatif.
BERAT_POSITIF = [
    ("milling_process_sources", "berat_kg"),
    ("pk_gudang2_intakes", "berat_kg"),
]
# `silo_storage` dan `drying_lot_batches` TIDAK punya kolom berat sendiri —
# beratnya tinggal di batch/lot yang ditautnya. Disebut di sini supaya yang
# berikutnya tak mencarinya lagi, dan supaya ketiadaannya terbaca sebagai
# fakta, bukan sebagai kelupaan.


def _periksa_pelanggar(sambung) -> list[str]:
    """Daftar pelanggaran yang SUDAH ada — dilaporkan, tak diubah."""
    masalah: list[str] = []
    for nama, tabel, kolom, syarat in INDEKS:
        if not _ada_tabel(sambung, tabel):
            continue
        baris = sambung.execute(sa.text(
            f"SELECT {kolom}, count(*) AS n FROM {tabel} "
            f"WHERE {syarat} GROUP BY {kolom} HAVING count(*) > 1 LIMIT 5"
        )).all()
        for nilai, n in baris:
            masalah.append(f"{tabel}.{kolom}={nilai} muncul {n}× (aturan {nama})")
    for tabel, kolom in BERAT_POSITIF:
        if not _ada_tabel(sambung, tabel):
            continue
        n = sambung.execute(sa.text(
            f"SELECT count(*) FROM {tabel} WHERE {kolom} IS NOT NULL AND {kolom} <= 0"
        )).scalar()
        if n:
            masalah.append(f"{tabel}.{kolom}: {n} baris ≤ 0")
    return masalah


def _ada_tabel(sambung, nama: str) -> bool:
    return bool(sambung.execute(sa.text(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = :t"
    ), {"t": nama}).scalar())


def upgrade() -> None:
    sambung = op.get_bind()

    masalah = _periksa_pelanggar(sambung)
    if masalah:
        raise RuntimeError(
            "Migrasi dihentikan: ada data yang sudah melanggar aturan yang "
            "akan dipasang. TIDAK ADA yang diubah atau dihapus — perbaiki "
            "barisnya lebih dulu, lalu jalankan lagi.\n  - "
            + "\n  - ".join(masalah)
        )

    for nama, tabel, kolom, syarat in INDEKS:
        if not _ada_tabel(sambung, tabel):
            continue
        op.execute(
            f"CREATE UNIQUE INDEX {nama} ON {tabel} ({kolom}) WHERE {syarat}"
        )
    for tabel, kolom in BERAT_POSITIF:
        if not _ada_tabel(sambung, tabel):
            continue
        op.execute(
            f"ALTER TABLE {tabel} ADD CONSTRAINT ck_{tabel}_berat_positif "
            f"CHECK ({kolom} IS NULL OR {kolom} > 0)"
        )


def downgrade() -> None:
    for tabel, _kolom in BERAT_POSITIF:
        op.execute(f"ALTER TABLE {tabel} DROP CONSTRAINT IF EXISTS ck_{tabel}_berat_positif")
    for nama, _t, _k, _s in INDEKS:
        op.execute(f"DROP INDEX IF EXISTS {nama}")
