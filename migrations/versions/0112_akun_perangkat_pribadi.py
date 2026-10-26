"""Akun baru berbawaan perangkat pribadi; akun yang ada tetap apa adanya.

HP operator dipakai masing-masing, keputusan pemilik 26 Oktober 2026.
DEFAULT basis data disamakan dengan paket identitas agar pembuat akun yang
tidak mengirim mode secara eksplisit juga memperoleh sesi perangkat pribadi.
Tidak ada UPDATE akun lama; perangkat bersama tetap pilihan yang sah.
"""
from alembic import op
import sqlalchemy as sa

revision = "0112_akun_perangkat_pribadi"
down_revision = "0111_pk_sendiri_50"
branch_labels = depends_on = None


def upgrade():
    op.alter_column("produksi_akun", "mode_perangkat",
                    existing_type=sa.String(10), existing_nullable=False,
                    server_default="pribadi")


def downgrade():
    op.alter_column("produksi_akun", "mode_perangkat",
                    existing_type=sa.String(10), existing_nullable=False,
                    server_default="bersama")
