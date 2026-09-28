"""Barang keluar / dikirim: catat dispatch + kurangi stok. Harga OPSIONAL —
penetapan harga & proses jual penuh ada di modul Penjualan.

item_type: finished_goods (karung) / byproduct_curah (bekatul, kg) / pk_langsung
(PK dari Gudang 1, kg→karung CEIL÷50; HANYA staff/admin). Stok BOLEH minus (warning).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_identitas.peran import G1

from app.peran import PERAN_ADMIN_KEATAS
from app.database import input_time
from app.models import MillingProcess, OutgoingItem, OutgoingRecord
from app.services.activity_log import log_activity
from app.services.codegen import next_outgoing_code
from app.services.transfer import pending_transfer_kg
from app.penggilingan.inventory.packaging import InventoryError, find_or_create_sku, get_standard
from app.penggilingan.inventory.finished_goods import (
    hitung_stok_bekatul,
    hitung_stok_finished_goods,
)


@dataclass
class OutgoingResult:
    kode: str
    label: str
    berat_kg: float
    jumlah_karung: int | None
    warning: str | None = None


# ⚠ TIGA FUNGSI DIBUANG 28 September 2026 — `kirim_finished_goods`,
# `kirim_bekatul`, `jual_pk_langsung`. Keputusan pemilik, atas usul QA.
#
# Barang keluar kini BERPERINTAH: Admin memerintah, operator memuat, Admin
# memverifikasi (`app.services.barang_keluar`). Ketiga fungsi ini mengeluarkan
# barang tanpa satu pun langkah itu, jadi membiarkannya hidup membuat seluruh
# rantai jadi SUKARELA — dan yang lewat pintu belakang tak terlihat di layar
# mana pun sebagai "keluar tanpa perintah".
#
# Rutenya dibuang bersamaan. Keduanya perlu: mencoret dari katalog tidak
# menutup pintu, sebab alamatnya bisa diketik dan lembar yang masih terbuka di
# layar orang masih bisa mengirim. Dijaga
# `tests/test_aksi_inventory.test_rute_ketiga_aksi_lama_ikut_hilang`.
#
# `_new_record` ikut hilang: satu-satunya pemakainya ketiga fungsi ini, dan
# ia pula yang membuat satu truk berisi tiga macam barang melahirkan tiga kode
# OUT- yang berbeda — ia memang membuat record BARU tiap kali dipanggil.

def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_barang_keluar(db: AsyncSession) -> str:
    rows = (
        await db.execute(
            select(OutgoingRecord).order_by(OutgoingRecord.id.desc()).limit(10)
        )
    ).scalars().all()
    if not rows:
        return "🚚 Belum ada barang keluar."
    lines = ["🚚 Barang keluar terakhir:"]
    for r in rows:
        items = (
            await db.execute(
                select(OutgoingItem).where(OutgoingItem.outgoing_record_id == r.id)
            )
        ).scalars().all()
        isi = ", ".join(f"{it.item_type} {_kg(float(it.berat_kg))}" for it in items)
        pembeli = f" → {r.nama_pembeli}" if r.nama_pembeli else ""
        lines.append(f"• {r.kode}: {isi}{pembeli}")
    return "\n".join(lines)