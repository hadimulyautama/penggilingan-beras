"""Modul Timbangan: revisi aturan cetak & kerahasiaan selisih.

Dua keputusan Direksi, 30 Agustus 2026:

  1. **Selisih tidak dicetak pada bukti PENGIRIMAN.** Sopir menerima berat
     barangnya; selisih kecil tidak perlu jadi bahan perdebatan di lokasi
     bongkar. Angkanya tetap tercatat di sistem.
  2. **Bukti timbang dicetak untuk SEMUA komoditas**, termasuk gabah. Sopir
     menandatanganinya sebagai saksi, jadi kertas itu alat bukti — bukan
     arsip sampingan.

Migrasi DATA, bukan skema. Diperlukan karena penyemaian master
(`service.pastikan_jenis`) sengaja hanya MENAMBAH baris yang belum ada dan
tidak pernah menimpa aturan yang sudah berjalan — sifat yang benar, tetapi
berarti revisi seperti ini harus ditulis eksplisit di sini agar tercatat.

Transaksi yang sudah tersimpan TIDAK berubah: masing-masing menyimpan salinan
aturannya sendiri.

Revision ID: 0024_timbangan_aturan_cetak
Revises: 0023_timbangan_config
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_timbangan_aturan_cetak"
down_revision: Union[str, None] = "0023_timbangan_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KELUAR = ("BERAS", "BROKEN", "MENIR", "BEKATUL", "REJECT")
GABAH = ("GABAH_BASAH", "GABAH_KERING")


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Pengiriman: hasil kontrol jadi internal, selisih tidak lagi tercetak.
    conn.execute(
        sa.text(
            "update timbangan_jenis set rahasia = true "
            "where kode in :kode and arah = 'KELUAR'"
        ).bindparams(sa.bindparam("kode", expanding=True)),
        {"kode": list(KELUAR)},
    )

    # 2. Gabah: buktinya tetap dicetak — sopir menandatangani sebagai saksi.
    conn.execute(
        sa.text(
            "update timbangan_jenis set cetak_bukti = true where kode in :kode"
        ).bindparams(sa.bindparam("kode", expanding=True)),
        {"kode": list(GABAH)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "update timbangan_jenis set rahasia = false "
            "where kode in :kode and arah = 'KELUAR'"
        ).bindparams(sa.bindparam("kode", expanding=True)),
        {"kode": list(KELUAR)},
    )
    conn.execute(
        sa.text(
            "update timbangan_jenis set cetak_bukti = false where kode in :kode"
        ).bindparams(sa.bindparam("kode", expanding=True)),
        {"kode": list(GABAH)},
    )
