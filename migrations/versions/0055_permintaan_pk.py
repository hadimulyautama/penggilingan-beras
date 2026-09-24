"""Operator Gudang 2 MEMINTA lot PK Gudang 1 dipindah — keputusan pemilik 24 Sep 2026.

Operator polesan kini melihat PK yang sudah jadi di Gudang 1 (bahan bakunya).
Yang belum ada: cara memberitahu Admin bahwa ia memerlukan lot tertentu. Hari
ini caranya telepon, dan yang lewat telepon tak pernah tercatat — tak ada yang
bisa menjawab "kenapa lot ini yang dipindah" seminggu kemudian.

Yang dicatat di sini PERMINTAAN, bukan izin. `peran.can_transfer_pk` tidak
berubah: yang memindahkan tetap Admin. Karena itu tabelnya berdiri sendiri dan
TIDAK menumpang `peristiwa`/`proyeksi_*` — buku besar itu mencatat apa yang
TERJADI pada barang, sedangkan ini antrean niat yang bisa ditolak dan bisa
kedaluwarsa. Menumpangkannya ke sana berarti buku besar yang memuat baris yang
tak pernah menggerakkan satu kilo pun.

SATU PERMINTAAN TERBUKA PER LOT, dijaga INDEKS PARSIAL — bukan oleh layar. Dua
operator yang menekan pada detik yang sama, atau satu operator yang menekan dua
kali karena halamannya lambat, tak boleh melahirkan dua kartu di layar Admin.
Pagar di layar tak bisa menjaga dua permintaan yang tiba bersamaan; pagar
sejenis yang sudah terbukti bekerja di app ini `uq_pk_gudang2_intakes_batch`,
dan ia ditemukan QA justru karena ia MENOLAK percobaan menghitung ganda.

Revision ID: 0055_permintaan_pk
Revises: 0054_bobot_belum_final
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055_permintaan_pk"
down_revision: Union[str, None] = "0054_bobot_belum_final"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Status permintaan. `terbuka` yang menempati indeks parsial; sisanya riwayat.
#: `selesai` = transfernya dicatat · `ditolak` = Admin menolak, sebabnya wajib ·
#: `gugur` = lotnya habis lewat jalan lain (dijual, atau terkirim seluruhnya).
STATUS = ("terbuka", "selesai", "ditolak", "gugur")


def upgrade() -> None:
    op.create_table(
        "permintaan_pk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("milling_process_id", sa.Integer(),
                  sa.ForeignKey("milling_process.id"), nullable=False),
        sa.Column("diminta_oleh", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("waktu_minta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="terbuka"),
        # Siapa yang menutupnya dan kenapa. Sebab WAJIB terisi saat ditolak —
        # permintaan yang lenyap tanpa kabar membuat orang menekannya lagi.
        sa.Column("ditutup_oleh", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("waktu_tutup", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sebab", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('terbuka','selesai','ditolak','gugur')", name="ck_permintaan_pk_status"),
        # Ditolak tanpa sebab = permintaan yang lenyap tanpa kabar.
        sa.CheckConstraint(
            "status <> 'ditolak' OR (sebab IS NOT NULL AND length(btrim(sebab)) > 0)",
            name="ck_permintaan_pk_sebab_tolak"),
    )
    op.create_index("ix_permintaan_pk_proses", "permintaan_pk", ["milling_process_id"])
    op.create_index("ix_permintaan_pk_status", "permintaan_pk", ["status"])
    # SATU yang terbuka per lot. Yang sudah ditutup boleh berkali-kali: lot yang
    # ditolak hari ini boleh diminta lagi besok dengan alasan yang berbeda.
    op.execute(
        "CREATE UNIQUE INDEX uq_permintaan_pk_terbuka ON permintaan_pk "
        "(milling_process_id) WHERE status = 'terbuka'"
    )


def downgrade() -> None:
    op.drop_index("uq_permintaan_pk_terbuka", table_name="permintaan_pk")
    op.drop_index("ix_permintaan_pk_status", table_name="permintaan_pk")
    op.drop_index("ix_permintaan_pk_proses", table_name="permintaan_pk")
    op.drop_table("permintaan_pk")
