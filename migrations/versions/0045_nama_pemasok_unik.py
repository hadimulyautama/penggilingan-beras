"""Satu nama pemasok, satu baris — selama ia belum dihapus.

Temuan QA X-20, 11 September 2026.

Ada TIGA penulis ke tabel `suppliers`, dan tak satu pun tahu tentang yang
lain: `find_or_create_supplier` di produksi, sinkron kontak Kledo di Kantor,
dan penyemai data uji. Ketiganya mencari-lalu-membuat, dan pencarian yang
mendahului pembuatan selalu bisa disalip.

Akibatnya dua baris bernama sama, dan sejak itu setiap laporan per pemasok
memecah riwayat satu orang jadi dua — tanpa ada yang salah di layar mana pun.
"Tanpa Nama" paling cepat menumpuk: ia nilai cadangan ketika tiket timbang tak
menyebut pihaknya.

Indeks unik PARSIAL (`WHERE deleted_at IS NULL`): pemasok yang sudah dihapus
boleh bernama sama dengan yang hidup — itulah gunanya soft delete, dan
melarangnya berarti nama yang pernah dipakai terkunci selamanya.

Perbandingannya `lower(...)`: "H. Anton" dan "h. anton" adalah orang yang
sama bagi siapa pun yang membacanya, dan orang itulah yang laporannya terbelah.

Migrasi ini GAGAL bila sudah ada nama kembar — dan itu disengaja. Yang benar
adalah menggabungkannya lebih dulu dengan tangan (memindahkan transaksi ke
satu baris, lalu menghapus yang lain), bukan membiarkan migrasi memilih
sendiri mana yang dibuang. Pesannya menyebutkan nama-namanya.

Revision ID: 0045_nama_pemasok_unik
Revises: 0044_tipe_dan_indeks_master
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_nama_pemasok_unik"
down_revision: Union[str, None] = "0044_tipe_dan_indeks_master"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    kembar = conn.execute(sa.text("""
        SELECT lower(nama_supplier) AS nama, count(*) AS n
          FROM suppliers
         WHERE deleted_at IS NULL
         GROUP BY lower(nama_supplier)
        HAVING count(*) > 1
         ORDER BY n DESC, nama
    """)).all()
    if kembar:
        daftar = ", ".join(f"{n} ({c}×)" for n, c in kembar[:10])
        raise RuntimeError(
            "Ada nama pemasok kembar, dan migrasi ini tidak memilih sendiri "
            "mana yang dibuang — riwayat pembeliannya menempel pada baris "
            f"yang berbeda. Gabungkan dulu: {daftar}"
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_nama_hidup "
        "ON suppliers (lower(nama_supplier)) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_suppliers_nama_hidup")
