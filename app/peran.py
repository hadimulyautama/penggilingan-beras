"""Siapa boleh apa — tangga peran pabrik.

Dulu tinggal di `app/bots/common.py`, dari masa ketika Telegram adalah satu-
satunya pintu masuk. Sejak bot produksi dibubarkan (perintah pindah sepenuhnya
ke Pos Produksi), aturan peran tak boleh ikut mati bersamanya: seluruh webapp
bergantung padanya. Ia juga tak pernah benar-benar milik bot — ia aturan
perusahaan, dan menaruhnya di modul saluran membuat orang mengira begitu.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from hmu_core import User

#: Peran yang boleh melihat data uang. "staff" ada di sini sebagai peran LAMA:
#: sejak 3 September 2026 tangganya superadmin / admin / operator, dan baris
#: lama di `users` tidak boleh kehilangan akses gara-gara namanya berganti.
#: Semua peran DI ATAS operator — satu tempat, karena tangga ini sudah sekali
#: bocor. `superadmin` ditambahkan di puncak saat peran dikonsolidasi, tetapi
#: delapan gerbang masih menyebut ("staff","admin") satu per satu; akibatnya
#: peran TERTINGGI bisa mengerjakan LEBIH SEDIKIT daripada admin di bawahnya.
#: Tangga yang tidak menurun ke bawah bukan tangga.
PERAN_STAF_KEATAS = ("superadmin", "admin", "staff")

#: Setara "admin ke atas" — untuk gerbang yang dulu menulis `== "admin"`.
PERAN_ADMIN_KEATAS = ("superadmin", "admin")

#: Boleh melihat angka uang. Kebetulan sama isinya — tetapi disebut terpisah
#: supaya kalau suatu saat ada peran yang boleh bekerja tanpa melihat harga,
#: yang berubah cukup satu.
PERAN_UANG = PERAN_STAF_KEATAS


def can_see_financials(user: User | None) -> bool:
    """Direksi ke atas boleh melihat data uang (harga gabah, nilai total
    pembelian, HPP). Operator TIDAK boleh."""
    return bool(user) and user.role in PERAN_UANG


def can_transfer_pk(user: User | None) -> bool:
    """Pengiriman PK Gudang 1 → Gudang 2 oleh staff ke atas. Operator TIDAK boleh."""
    return bool(user) and user.role in PERAN_STAF_KEATAS


async def user_wh_scope(db: AsyncSession, user: User | None) -> str:
    """Lingkup akses gudang user:
    - 'all'  : staff/admin (lihat & kerjakan semua)
    - 'g1'   : operator Gudang 1 (hanya Gudang 1)
    - 'g2'   : operator Gudang 2 (hanya Gudang 2)
    - 'none' : operator tanpa gudang / lainnya.
    Operator Gudang 1 & 2 dipisah tegas: tak boleh lintas gudang."""
    if not user:
        return "none"
    if user.role in PERAN_STAF_KEATAS:
        return "all"
    if user.role == "operator" and user.default_warehouse_id:
        from hmu_core import Warehouse
        wh = await db.get(Warehouse, user.default_warehouse_id)
        nama = (wh.nama_gudang if wh else "") or ""
        if nama.startswith("Gudang 1"):
            return "g1"
        if nama.startswith("Gudang 2"):
            return "g2"
    return "none"
