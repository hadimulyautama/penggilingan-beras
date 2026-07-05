"""QC uji lab PK luar (penyusutan/butir kuning/catatan) + retur PK ditolak (REJ-)

Revision ID: 0012_pk_rejection_lab_qc
Revises: 0011_outgoing
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_pk_rejection_lab_qc"
down_revision: Union[str, None] = "0011_outgoing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Uji lab tambahan pada QC PK luar
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("penyusutan_persen", sa.Numeric(5, 2)),
    )
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("butir_kuning", sa.String(10)),
    )
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("catatan_lab", sa.String(255)),
    )
    op.add_column(
        "pk_purchase_verifications",
        sa.Column("alasan_tolak", sa.String(255)),
    )
    # Register retur PK ditolak (dikembalikan ke supplier)
    op.create_table(
        "pk_rejections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(20), nullable=False, unique=True),
        sa.Column(
            "pk_purchase_batch_id", sa.Integer,
            sa.ForeignKey("pk_purchase_batches.id"), nullable=False, unique=True,
        ),
        sa.Column("berat_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("no_polisi_truk", sa.String(20)),
        sa.Column("alasan", sa.String(255)),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("pk_rejections")
    op.drop_column("pk_purchase_verifications", "alasan_tolak")
    op.drop_column("pk_purchase_verifications", "catatan_lab")
    op.drop_column("pk_purchase_verifications", "butir_kuning")
    op.drop_column("pk_purchase_verifications", "penyusutan_persen")
