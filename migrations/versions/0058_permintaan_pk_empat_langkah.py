"""Minta lot PK jadi PROSES empat langkah — keputusan pemilik 25 September 2026.

Sampai hari ini "minta lot" cuma PENGINGAT di layar Admin: operator Gudang 2
menekannya, lalu Admin sendiri yang mengerjakan seluruhnya dalam satu langkah,
dan permintaannya menutup dirinya sendiri begitu transfer dicatat. Operator
Gudang 1 tak pernah terlibat — bukan karena dilarang di tengah jalan, melainkan
karena ia tak punya kemampuan itu sama sekali. Dan yang meminta tak pernah
diberi kabar lagi sesudah menekan tombolnya.

Empat langkah, empat tangan:

    1 MINTA     operator G2  → diminta
    2 ACC       admin        → disetujui   (menetapkan TUJUAN dan BOBOT)
      atau TOLAK              → ditolak    (sebab WAJIB, sudah ada)
    3 KIRIM     operator G1  → dikirim     ← DI SINI BARANGNYA BERPINDAH
    4 TUTUP     admin        → selesai     (boleh mengubah bobotnya)

`gugur` tetap: lot bisa habis lewat jalan lain.

TIGA KEPUTUSAN PEMILIK YANG MEMBENTUK KOLOMNYA:

  (a) Barangnya berpindah saat operator G1 mengeksekusi, bukan saat admin
      menutup — Gudang 2 harus bisa langsung menyosohnya.
  (b) Bila bobot G1 berbeda dari bobot admin, ANGKA ADMIN yang berlaku, tetapi
      angka G1 TETAP DISIMPAN (`berat_kirim_kg`) supaya selisihnya bisa
      ditelusuri. Karena itu kolomnya tiga: disetujui, dikirim, final.
  (c) Satu permintaan = satu eksekusi. Karena itu indeks parsialnya melebar ke
      SELURUH keadaan yang masih berjalan, bukan hanya yang pertama — tanpa
      itu satu lot bisa punya dua permintaan berjalan sekaligus dan butir (c)
      patah di basis data, bukan di layar.

TUJUANNYA MEMAKAI KOSAKATA 25 SEPTEMBER (migrasi 0057), bukan `silo_a`/
`silo_b` yang disebut di brief: jenis tempatnya (`silo`/`ditumpuk`) plus
rujukan `silo_id`. Menulis nama silo ke dalam kolom baru hari ini berarti
melahirkan kembali kosakata yang baru saja dipensiunkan pagi tadi — dan silo
Gudang 2 ketiga takkan punya kata lagi.

Revision ID: 0058_permintaan_pk_empat_langkah
Revises: 0057_tujuan_pk_g2_rujukan_silo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_permintaan_pk_empat_langkah"
down_revision: Union[str, None] = "0057_tujuan_pk_g2_rujukan_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Keadaan yang masih BERJALAN — yang dijaga indeks parsial.
HIDUP = ("diminta", "disetujui", "dikirim")
#: Seluruh keadaan yang sah.
SEMUA = HIDUP + ("selesai", "ditolak", "gugur")


def upgrade() -> None:
    for kolom in (
        sa.Column("tujuan", sa.String(12)),
        sa.Column("silo_id", sa.Integer(), sa.ForeignKey("silos.id")),
        sa.Column("berat_setuju_kg", sa.Numeric(12, 2)),
        sa.Column("disetujui_oleh", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("waktu_setuju", sa.DateTime(timezone=True)),
        sa.Column("berat_kirim_kg", sa.Numeric(12, 2)),
        sa.Column("dikirim_oleh", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("waktu_kirim", sa.DateTime(timezone=True)),
        sa.Column("internal_transfer_id", sa.Integer(),
                  sa.ForeignKey("internal_transfers.id")),
        sa.Column("berat_final_kg", sa.Numeric(12, 2)),
    ):
        op.add_column("permintaan_pk", kolom)

    # SATU nama untuk keadaan pertama, bukan dua. `terbuka` lahir saat
    # keadaannya memang cuma "sudah diminta, belum ditutup"; sekarang ada tiga
    # keadaan yang sama-sama terbuka, dan nama itu berhenti menjelaskan apa pun.
    op.execute("UPDATE permintaan_pk SET status = 'diminta' WHERE status = 'terbuka'")

    op.drop_constraint("ck_permintaan_pk_status", "permintaan_pk", type_="check")
    op.create_check_constraint(
        "ck_permintaan_pk_status", "permintaan_pk",
        "status IN (" + ", ".join(f"'{s}'" for s in SEMUA) + ")")

    # ── Satu permintaan BERJALAN per lot ──
    #
    # Indeks lama hanya menjaga `terbuka`. Dengan tiga keadaan berjalan, ia
    # akan membiarkan lot yang sudah di-ACC diminta lagi — dan dua permintaan
    # berjalan atas satu lot berarti dua perpindahan atas PK yang sama.
    op.execute("DROP INDEX IF EXISTS uq_permintaan_pk_terbuka")
    op.execute(
        "CREATE UNIQUE INDEX uq_permintaan_pk_hidup ON permintaan_pk "
        "(milling_process_id) WHERE status IN ("
        + ", ".join(f"'{s}'" for s in HIDUP) + ")")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_permintaan_pk_hidup")
    # Keadaan yang belum ada sebelum ini dikembalikan ke keadaan pertama:
    # 'disetujui' dan 'dikirim' tak punya padanan di skema lama, dan menebak
    # padanannya berarti memutuskan atas nama orang yang sedang mengerjakannya.
    op.execute("UPDATE permintaan_pk SET status = 'terbuka' "
               "WHERE status IN ('diminta', 'disetujui', 'dikirim')")
    op.drop_constraint("ck_permintaan_pk_status", "permintaan_pk", type_="check")
    op.create_check_constraint(
        "ck_permintaan_pk_status", "permintaan_pk",
        "status IN ('terbuka','selesai','ditolak','gugur')")
    op.execute(
        "CREATE UNIQUE INDEX uq_permintaan_pk_terbuka ON permintaan_pk "
        "(milling_process_id) WHERE status = 'terbuka'")
    for nama in ("berat_final_kg", "internal_transfer_id", "waktu_kirim",
                 "dikirim_oleh", "berat_kirim_kg", "waktu_setuju",
                 "disetujui_oleh", "berat_setuju_kg", "silo_id", "tujuan"):
        op.drop_column("permintaan_pk", nama)
