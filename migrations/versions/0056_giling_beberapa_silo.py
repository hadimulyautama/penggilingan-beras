"""Satu lot giling boleh datang dari BEBERAPA silo — keputusan pemilik 24 Sep 2026.

"sering", kata pemilik, dan "hasilnya 1 lot". Yang menghalangi bukan bentuk
datanya: `milling_process_sources` sudah satu baris per sumber, dan himpunan
silo sebuah proses SUDAH bisa diturunkan (sources → silo_storage → silo_id).
Tak ada tabel baru yang perlu lahir, dan tak ada angka yang perlu disimpan dua
kali.

YANG PERLU MIGRASI HANYA PENJAGAANNYA.

`uq_milling_process_silo_proses` menjaga "satu giling berjalan per silo" lewat
kolom tunggal `milling_process.silo_id`. Aturannya TETAP BENAR dan harus tetap
ada — dua giling atas gabah yang sama adalah angka yang bohong dua kali — tapi
kolom itu kini menyebut silo PERTAMA saja. Ia akan menjaga silo pertama dan
membiarkan silo kedua terbuka, yaitu persis kerusakan yang paling mahal:
kartunya masih bertombol "Mulai giling" padahal gabahnya sudah di mesin.

Penjagaannya pindah ke baris silonya sendiri: `silo_storage.milling_process_id`
— klaim atas satu baris isi silo oleh satu proses yang sedang berjalan.

KENAPA BUKAN INDEKS UNIK PARSIAL, seperti pagar-pagar lain di app ini:
syaratnya ("prosesnya berstatus 'proses'") tinggal di baris TABEL LAIN, dan
indeks hanya bisa menguji baris miliknya sendiri. Pemicu juga tak menolong —
di READ COMMITTED ia tak melihat baris tetangga yang belum di-commit, jadi dua
operator yang menekan bersamaan tetap sama-sama lolos.

Yang dipakai: SATU kolom pada baris yang diperebutkan, direbut dengan
`UPDATE … WHERE milling_process_id IS NULL`. Postgres mengunci barisnya, lalu
MENGUJI ULANG syaratnya sesudah kunci didapat — jadi penekan kedua menerima
"0 baris", bukan klaim kedua yang sama-sama berhasil. Pagarnya di basis data,
bukan di pemeriksaan-di-depan yang bisa dilewati dua orang sekaligus.

DATA LAMA AMAN. Proses satu-silo punya satu baris sumber, jadi himpunannya
berisi satu dan hasilnya sama dengan sekarang. Proses yang SEDANG berjalan saat
migrasi ini dijalankan diberi klaimnya di sini, supaya silonya tidak mendadak
terbuka lagi begitu versi baru menyala.

Revision ID: 0056_giling_beberapa_silo
Revises: 0055_permintaan_pk
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_giling_beberapa_silo"
down_revision: Union[str, None] = "0055_permintaan_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("silo_storage", sa.Column("milling_process_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_silo_storage_giling", "silo_storage", "milling_process",
        ["milling_process_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_silo_storage_giling", "silo_storage", ["milling_process_id"],
                    postgresql_where=sa.text("milling_process_id IS NOT NULL"))

    # ── Proses yang SEDANG berjalan diberi klaimnya ──
    #
    # Tanpa ini, giling yang sedang berputar saat deploy kehilangan pagarnya:
    # indeks lama sudah dijatuhkan, klaim barunya belum ada, dan silonya
    # ditawarkan lagi kepada operator yang sedang menunggui mesinnya sendiri.
    #
    # Dua jalan, dan keduanya perlu: `milling_process_sources` untuk proses
    # yang lahir sesudah tabel itu ada, dan `milling_process.silo_storage_id`
    # untuk yang lebih tua (penunjuk tunggal peninggalan).
    op.execute("""
        UPDATE silo_storage s SET milling_process_id = p.id
        FROM milling_process p
        JOIN milling_process_sources ms ON ms.milling_process_id = p.id
        WHERE p.status = 'proses' AND ms.silo_storage_id = s.id
          AND s.milling_process_id IS NULL
    """)
    op.execute("""
        UPDATE silo_storage s SET milling_process_id = p.id
        FROM milling_process p
        WHERE p.status = 'proses' AND p.silo_storage_id = s.id
          AND s.milling_process_id IS NULL
    """)

    # Yang dijatuhkan TERAKHIR: selama klaimnya belum terpasang, indeks lama
    # masih satu-satunya yang menjaga apa pun.
    op.drop_index("uq_milling_process_silo_proses", table_name="milling_process")


def downgrade() -> None:
    # Indeks lama hanya bisa berdiri kembali bila tak ada proses berjalan yang
    # memakai dua silo — kalau ada, dialah yang harus diselesaikan dulu; itu
    # keputusan orang, bukan keputusan migrasi.
    op.create_index("uq_milling_process_silo_proses", "milling_process", ["silo_id"],
                    unique=True,
                    postgresql_where=sa.text("silo_id IS NOT NULL AND status = 'proses'"))
    op.drop_index("ix_silo_storage_giling", table_name="silo_storage")
    op.drop_constraint("fk_silo_storage_giling", "silo_storage", type_="foreignkey")
    op.drop_column("silo_storage", "milling_process_id")
