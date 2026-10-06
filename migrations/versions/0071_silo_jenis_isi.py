"""`silos.jenis_isi` ('pk' / 'broken') — keputusan pemilik 6 Oktober 2026.

Broken (PK yang sudah disosoh, patah) dapat silonya sendiri: jenis bahan
sebuah proses sosoh diturunkan dari silo sumbernya, bukan dicatat
per-pemakaian. Lihat docstring `hmu_core.models.Silo`.

⚠ Skema `silos` "dimiliki" paket `hmu_core` (repo `core/`, keputusan pemilik
13 September 2026) — tetapi pelari migrasinya BELUM dipindahkan ke sana
("tahap kecil sendiri", `core/CLAUDE.md`), dan tabelnya sendiri lahir dari
chain migrasi LAMA repo ini (`0001_phase1_gudang1`). Kolom baru ini karena
itu ditambahkan DI SINI — chain yang benar-benar dijalankan `alembic upgrade
head` saat deploy (`docker/entrypoint.sh`) dan saat uji Postgres dibangun
(`tests/pg/conftest.py`) — bukan di chain core, yang isinya dokumenter untuk
kasus ini (lihat `core/migrations/versions/0003_silo_jenis_isi.py`, yang
justru memperingatkan JANGAN di-upgrade atas DB yang sudah dimigrasikan dari
sini — pola yang sama dengan `core/migrations/versions/0001_baseline_master`).

Bawaannya 'pk': SELURUH silo yang ada hari ini (Gudang 1 maupun Gudang 2)
memang berisi PK/gabah, dan baris lama tak boleh berubah arti oleh kolom
yang baru ditambahkan.

Revision ID: 0071_silo_jenis_isi
Revises: 0070_pembebasan_silo_giling
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071_silo_jenis_isi"
down_revision: Union[str, None] = "0070_pembebasan_silo_giling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "silos",
        sa.Column("jenis_isi", sa.String(20), nullable=False, server_default="pk"),
    )


def downgrade() -> None:
    op.drop_column("silos", "jenis_isi")
