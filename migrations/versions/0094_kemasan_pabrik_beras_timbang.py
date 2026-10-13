"""Pisahkan pemilik kemasan dari pemilik beras masuk timbang."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0094_kemasan_pabrik_beras_timbang"
down_revision: Union[str, None] = "0093_hasil_samping_ke_silo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "finished_goods_stock",
        sa.Column("kemasan_dari_pabrik", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    # Catatan beras timbang yang sudah sempat dibuat memakai karung pabrik
    # juga harus mulai mengurangi stok karung pabrik setelah migrasi.
    op.execute(sa.text("""
        UPDATE finished_goods_stock
        SET kemasan_dari_pabrik = TRUE
        WHERE source_type = 'timbangan'
    """))


def downgrade() -> None:
    op.drop_column("finished_goods_stock", "kemasan_dari_pabrik")
