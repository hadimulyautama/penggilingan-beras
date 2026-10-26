"""Induk perjalanan bersama; perintah dan item historis tetap utuh."""
from alembic import op
import sqlalchemy as sa

revision = "0114_kiriman_pelanggan"
down_revision = "0113_broken_karung_dibongkar"
branch_labels = depends_on = None


def upgrade():
    op.create_table("kiriman_keluar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timbangan_transaksi_id", sa.Integer(), unique=True),
        sa.Column("metode", sa.String(20)),
        sa.Column("no_polisi", sa.String(20)),
        sa.Column("nama_ekspedisi", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("outgoing_records", sa.Column("kiriman_id", sa.Integer(),
        sa.ForeignKey("kiriman_keluar.id")))
    op.create_index("ix_outgoing_records_kiriman_id", "outgoing_records", ["kiriman_id"])
    op.create_unique_constraint("uq_outgoing_kiriman_pelanggan", "outgoing_records", ["kiriman_id", "pelanggan_id"])
    op.create_check_constraint("ck_outgoing_tiket_tunggal", "outgoing_records",
        "kiriman_id IS NULL OR timbangan_transaksi_id IS NULL")


def downgrade():
    # Jangan memutus kiriman yang telah digunakan hanya demi mundur versi.
    conn = op.get_bind()
    if conn.scalar(sa.text("SELECT count(*) FROM outgoing_records WHERE kiriman_id IS NOT NULL")):
        raise RuntimeError("Kiriman bersama sudah digunakan; pulihkan aplikasi yang kompatibel tanpa menghapus relasi pelanggan.")
    op.drop_constraint("ck_outgoing_tiket_tunggal", "outgoing_records", type_="check")
    op.drop_constraint("uq_outgoing_kiriman_pelanggan", "outgoing_records", type_="unique")
    op.drop_index("ix_outgoing_records_kiriman_id", "outgoing_records")
    op.drop_column("outgoing_records", "kiriman_id")
    op.drop_table("kiriman_keluar")
