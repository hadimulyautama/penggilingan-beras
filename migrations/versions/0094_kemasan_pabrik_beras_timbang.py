"""Kecualikan beras timbang yang sudah berkemasan dari pemakaian stok karung."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0094_kemasan_pabrik_beras_timbang"
down_revision: Union[str, None] = "0093_hasil_samping_ke_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic membuat kolom ini VARCHAR(32) secara bawaan. Revisi ini lebih
    # panjang, dan Alembic memperbarui version_num setelah upgrade() selesai;
    # perbesar kolom di dalam migrasi agar pembaruan revisinya tidak gagal.
    op.alter_column(
        "alembic_version", "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "finished_goods_stock",
        sa.Column("kemasan_mengurangi_stok", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )
    # Beras dari tiket timbang sudah tiba dengan kemasannya, jadi jumlah
    # karungnya tidak dihitung sebagai pemakaian persediaan mana pun.
    op.execute(sa.text("""
        UPDATE finished_goods_stock
        SET kemasan_mengurangi_stok = FALSE
        WHERE source_type = 'timbangan'
    """))


def downgrade() -> None:
    op.drop_column("finished_goods_stock", "kemasan_mengurangi_stok")
