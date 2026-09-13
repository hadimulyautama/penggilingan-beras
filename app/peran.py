"""Siapa boleh apa — tangga peran pabrik, kini dari paket `hmu_identitas`.

Dulu tinggal di `app/bots/common.py`, lalu di sini sendiri; sejak Tahap 2
rancang ulang (13 September 2026) tangganya SATU untuk lima repo di
`hmu_identitas.peran`. Modul ini tinggal mengekspor ulang nama-nama yang
sudah dipakai seluruh webapp, ditambah dua aturan yang memang milik pabrik
(uang dan pengiriman PK).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from hmu_core import User
from hmu_identitas import peran as P
from hmu_identitas.peran import (PERAN_ADMIN_KEATAS, PERAN_STAF_KEATAS,  # noqa: F401
                                 PERAN_UANG)


def can_see_financials(user: User | None) -> bool:
    """Admin ke atas boleh melihat data uang (harga gabah, nilai total
    pembelian, HPP). Operator TIDAK boleh."""
    return bool(user) and P.normal(user.role) in PERAN_UANG


def can_transfer_pk(user: User | None) -> bool:
    """Pengiriman PK Gudang 1 → Gudang 2 oleh admin ke atas. Operator TIDAK boleh."""
    return bool(user) and P.staf_keatas(user.role)


async def user_wh_scope(db: AsyncSession, user: User | None) -> str:
    """Lingkup akses gudang user: 'all' / 'g1' / 'g2' / 'none'.

    Nilai lama dipertahankan untuk pemanggilnya; aturannya dari
    `hmu_identitas.peran.lingkup` (operator melekat pada satu gudang).
    """
    if not user:
        return "none"
    nama = None
    if P.operator_saja(user.role) and user.default_warehouse_id:
        from hmu_core import Warehouse
        wh = await db.get(Warehouse, user.default_warehouse_id)
        nama = wh.nama_gudang if wh else None
    return {P.SEMUA: "all", P.G1: "g1", P.G2: "g2"}.get(P.lingkup(user.role, nama), "none")
