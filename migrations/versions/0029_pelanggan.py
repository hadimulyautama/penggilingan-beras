"""Master pelanggan, disinkron dari kontak Kledo bertipe 3.

Sengaja tabel tersendiri, bukan kolom tipe pada `suppliers`. Alasannya ada di
docstring model `Pelanggan`: satu kontak Kledo boleh sekaligus vendor dan
pelanggan — 24 kontak memang begitu — tetapi bagi pos timbang yang menentukan
adalah perannya pada transaksi itu.

Bentuknya sengaja sama persis dengan `suppliers` supaya sinkronisasi keduanya
memakai satu kode yang sama, bukan dua salinan yang lambat laun berbeda.

Revision ID: 0027_pelanggan
Revises: 0028_batch_bobot_nullable
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_pelanggan"
down_revision: Union[str, None] = "0028_batch_bobot_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pelanggan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nama_pelanggan", sa.String(150), nullable=False),
        sa.Column("no_telfon", sa.String(30)),
        sa.Column("alamat", sa.Text()),
        sa.Column("status", sa.String(20), server_default="aktif", nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sa.Column("kledo_contact_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pelanggan_kledo_contact_id", "pelanggan",
                    ["kledo_contact_id"])


def downgrade() -> None:
    op.drop_index("ix_pelanggan_kledo_contact_id", table_name="pelanggan")
    op.drop_table("pelanggan")
