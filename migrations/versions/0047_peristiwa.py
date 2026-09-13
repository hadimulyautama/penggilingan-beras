"""Buku besar peristiwa (tambah-saja) + proyeksi gabah masuk — Tahap 3.

Rancang ulang 2026, tahap 3 (disetujui pemilik 13 September 2026). Temuan
yang dijawab: P-K-01, P-K-08, P-K-09, P-K-10, P-K-21 — semuanya lahir dari
pencatatan yang menimpa angka dan menghapus baris.

  · `peristiwa`: id, jenis, waktu (berzona), pelaku, kunci_kiriman UNIK,
    muatan JSONB, membatalkan_id (nullable, UNIK). TAMBAH-SAJA: trigger
    menolak UPDATE dan DELETE. TRUNCATE sengaja tidak dihalangi (dipakai
    basis data uji) — di pabrik tak ada jalur yang memanggilnya.
  · `proyeksi_gabah_masuk`: diturunkan dari peristiwa `gabah_masuk`; bisa
    dibangun ulang dari nol (`scripts/bangun_ulang_proyeksi.py`). Indeks
    unik parsial: satu tiket timbang hanya punya satu pencatatan yang hidup.
  · `purchase_batches.peristiwa_id`: penunjuk cermin → peristiwa. Baris
    yang ada dibiarkan kosong (jalur lama).

Tabel `timbangan_*` dan `kantor_*` tidak disentuh. Tak ada baris yang diubah.

Revision ID: 0047_peristiwa
Revises: 0046_gudang2_operator
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047_peristiwa"
down_revision: Union[str, None] = "0046_gudang2_operator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "peristiwa",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("jenis", sa.String(40), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("pelaku_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("kunci_kiriman", sa.String(120), nullable=False, unique=True),
        sa.Column("muatan", postgresql.JSONB(), nullable=False),
        sa.Column("membatalkan_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id"), unique=True),
    )
    op.create_index("ix_peristiwa_jenis_waktu", "peristiwa", ["jenis", "waktu"])
    op.create_index("ix_peristiwa_membatalkan", "peristiwa", ["membatalkan_id"])
    op.execute("""
        CREATE FUNCTION peristiwa_tambah_saja() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'peristiwa hanya bertambah: % pada id % ditolak', TG_OP, OLD.id;
        END $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER peristiwa_tambah_saja
        BEFORE UPDATE OR DELETE ON peristiwa
        FOR EACH ROW EXECUTE FUNCTION peristiwa_tambah_saja();
    """)

    op.create_table(
        "proyeksi_gabah_masuk",
        sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id"), primary_key=True),
        sa.Column("kode_batch", sa.String(20), nullable=False),
        sa.Column("timbangan_transaksi_id", sa.Integer()),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id")),
        sa.Column("nama_supplier", sa.String(150)),
        sa.Column("berat_kg", sa.Numeric(12, 2)),
        sa.Column("sumber_berat", sa.String(12), nullable=False),
        sa.Column("kondisi", sa.String(10), nullable=False),
        sa.Column("no_polisi", sa.String(20)),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pelaku_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dibatalkan_peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")),
        sa.Column("purchase_batch_id", sa.Integer()),
        sa.CheckConstraint("berat_kg IS NULL OR berat_kg >= 0", name="ck_proyeksi_gabah_masuk_berat"),
        sa.CheckConstraint("status IN ('tercatat', 'dibatalkan')", name="ck_proyeksi_gabah_masuk_status"),
    )
    op.create_index("uq_proyeksi_gabah_masuk_tiket_hidup", "proyeksi_gabah_masuk",
                    ["timbangan_transaksi_id"], unique=True,
                    postgresql_where=sa.text("status = 'tercatat'"))
    op.create_index("ix_proyeksi_gabah_masuk_tanggal", "proyeksi_gabah_masuk", ["tanggal"])

    op.add_column("purchase_batches",
                  sa.Column("peristiwa_id", sa.BigInteger(), sa.ForeignKey("peristiwa.id")))


def downgrade() -> None:
    op.drop_column("purchase_batches", "peristiwa_id")
    op.drop_index("ix_proyeksi_gabah_masuk_tanggal", table_name="proyeksi_gabah_masuk")
    op.drop_index("uq_proyeksi_gabah_masuk_tiket_hidup", table_name="proyeksi_gabah_masuk")
    op.drop_table("proyeksi_gabah_masuk")
    op.execute("DROP TRIGGER IF EXISTS peristiwa_tambah_saja ON peristiwa")
    op.execute("DROP FUNCTION IF EXISTS peristiwa_tambah_saja()")
    op.drop_index("ix_peristiwa_membatalkan", table_name="peristiwa")
    op.drop_index("ix_peristiwa_jenis_waktu", table_name="peristiwa")
    op.drop_table("peristiwa")
