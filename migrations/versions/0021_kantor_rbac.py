"""kantor_role + kantor_user_role + kantor_grant (Tahap 1: RBAC registry)

Revision ID: 0021_kantor_rbac
Revises: 0020_kantor_biaya
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_kantor_rbac"
down_revision: Union[str, None] = "0020_kantor_biaya"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kantor_role",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(40), nullable=False, unique=True),
        sa.Column("nama", sa.String(120), nullable=False),
        sa.Column("keterangan", sa.String(255)),
        sa.Column("status", sa.String(12), server_default="aktif", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "kantor_user_role",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_kode", sa.String(40), nullable=False),
        sa.Column("atasan_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(12), server_default="aktif", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "role_kode", name="uq_user_role"),
    )
    op.create_table(
        "kantor_grant",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("role_kode", sa.String(40), nullable=False),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(10), server_default="none", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("role_kode", "domain", name="uq_role_domain"),
    )


def downgrade() -> None:
    op.drop_table("kantor_grant")
    op.drop_table("kantor_user_role")
    op.drop_table("kantor_role")
