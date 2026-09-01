"""Master data — kini didefinisikan di paket BERSAMA `hmu_core` (submodule `core`).

File ini tinggal RE-EXPORT agar semua `from app.models.master import X` yang sudah ada
tetap jalan tanpa perubahan. Definisi tunggal (sumber kebenaran) ada di `hmu_core.models`,
dipakai bersama oleh produksi, kantor, dan timbangan. Skema master dikelola oleh chain
migrasi core (`alembic_version_core`), bukan chain aplikasi.
"""
from hmu_core import Dryer, Pelanggan, Silo, Supplier, User, Warehouse

__all__ = ["Warehouse", "User", "Supplier", "Pelanggan", "Silo", "Dryer"]
