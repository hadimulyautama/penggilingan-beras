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

Bila sudah ada nama kembar, indeksnya TIDAK dibuat dan migrasi tetap lanjut,
dengan peringatan yang menyebut nama-namanya.

Versi pertama migrasi ini melempar galat — niatnya benar (menggabungkan
riwayat pembelian bukan keputusan yang boleh diambil migrasi sendiri), tetapi
akibatnya salah. Entrypoint berhenti dengan exit 1 bila migrasi gagal, jadi
satu nama kembar di basis data akan membuat SELURUH pabrik tak bisa menyala —
dan yang hilang bukan indeksnya melainkan hari kerjanya.

Indeks yang belum ada bisa ditambahkan kapan saja sesudah namanya
digabungkan; layanan yang tak menyala tidak bisa menunggu.

Revision ID: 0045_nama_pemasok_unik
Revises: 0044_tipe_dan_indeks_master
"""
from typing import Sequence, Union

import logging

import sqlalchemy as sa
from alembic import op

log = logging.getLogger("alembic.migrasi")

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
        log.warning(
            "INDEKS NAMA PEMASOK TIDAK DIBUAT — masih ada nama kembar: %s. "
            "Gabungkan dulu (pindahkan transaksinya ke satu baris, lalu hapus "
            "yang lain), setelah itu jalankan: CREATE UNIQUE INDEX "
            "uq_suppliers_nama_hidup ON suppliers (lower(nama_supplier)) "
            "WHERE deleted_at IS NULL;", daftar,
        )
        return
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_nama_hidup "
        "ON suppliers (lower(nama_supplier)) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_suppliers_nama_hidup")
