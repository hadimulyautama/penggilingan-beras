"""Simpan target kadar air bawaan pada masing-masing mesin pengering."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0091_target_kadar_air_per_dryer"
down_revision: Union[str, None] = "0090_silo_aktif"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("dryers", sa.Column("target_kadar_air", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("dryers", "target_kadar_air")
