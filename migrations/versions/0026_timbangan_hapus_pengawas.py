"""Modul Timbangan: hapus peran Pengawas, sisakan Admin dan Petugas.

Keputusan Direksi 30 Agustus 2026. Sejak rekapitulasi — ringkasan, monitoring,
ekspor, daftar catatan — menjadi wewenang Admin, peran Pengawas tidak lagi
memiliki satu pun kemampuan yang tidak dimiliki petugas. Peran yang tidak
berarti apa-apa lebih buruk daripada tidak ada: ia terlihat seperti pengaman
padahal bukan.

Akun yang terlanjur berperan PENGAWAS diturunkan menjadi PETUGAS, bukan
dinaikkan menjadi ADMIN. Menurunkan hanya menutup pintu yang memang sudah
tidak berfungsi; menaikkan akan diam-diam memberi wewenang penuh atas
rekapitulasi, pembatalan, dan pengelolaan pengguna kepada orang yang tidak
pernah diputuskan menerimanya.

Turun-versi mengembalikan nama perannya, tetapi TIDAK bisa mengembalikan
siapa yang dulu Pengawas dan siapa yang memang petugas — keduanya sudah
menjadi nilai yang sama. Yang bisa dipakai memulihkan itu hanya jejak audit.

Revision ID: 0026_timbangan_hapus_pengawas
Revises: 0025_timbangan_cetak_format
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0026_timbangan_hapus_pengawas"
down_revision: Union[str, None] = "0025_timbangan_cetak_format"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE timbangan_akun SET role = 'PETUGAS' WHERE role = 'PENGAWAS'"
    )


def downgrade() -> None:
    """Tidak ada yang bisa dipulihkan — lihat catatan di atas."""
