"""kantor_config + kantor_llm_usage (Tahap 0: pengaman biaya LLM)

Revision ID: 0020_kantor_biaya
Revises: 0019_kantor_heartbeat
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_kantor_biaya"
down_revision: Union[str, None] = "0019_kantor_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kantor_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kunci", sa.String(60), nullable=False, unique=True),
        sa.Column("nilai", sa.String(255)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_table(
        "kantor_llm_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("pemanggil", sa.String(60), server_default="?", nullable=False),
        sa.Column("input_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("est_biaya_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("status", sa.String(12), server_default="ok", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_kantor_llm_usage_created_at", "kantor_llm_usage", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_kantor_llm_usage_created_at", table_name="kantor_llm_usage")
    op.drop_table("kantor_llm_usage")
    op.drop_table("kantor_config")
