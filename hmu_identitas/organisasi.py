"""Pembentuk konteks organisasi baca-saja; belum dipakai gerbang aplikasi.

user_id wajib berasal dari sesi yang sudah diverifikasi pemanggil. Menerima
company_id dari formulir tidak memberikan akses tanpa keanggotaan yang sah.
Tidak ada fallback ke perusahaan pertama, gudang bawaan, atau peran global.
"""
from dataclasses import dataclass
from sqlalchemy import and_, func, select
from hmu_core import User, Warehouse
from hmu_core.organisasi import Perusahaan, LokasiPabrik, KeanggotaanPerusahaan, PenempatanGudang
from . import peran as P


class OrganisasiTidakDiizinkan(PermissionError):
    pass


@dataclass(frozen=True)
class KonteksKerja:
    """Nilai hasil validasi; bukan token autentikasi atau bukti akses mandiri."""
    user_id: int
    company_id: int
    lokasi_pabrik_id: int
    warehouse_id: int
    keanggotaan_id: int
    peran: str


async def konteks_kerja(db, *, user_id: int, company_id: int,
                      lokasi_pabrik_id: int, warehouse_id: int) -> KonteksKerja:
    pesan = 'Perusahaan, lokasi, atau gudang kerja tidak tersedia untuk akun ini.'
    ids = (user_id, company_id, lokasi_pabrik_id, warehouse_id)
    if any(type(i) is not int or i <= 0 for i in ids):
        raise OrganisasiTidakDiizinkan(pesan)
    m, s, w = KeanggotaanPerusahaan, LokasiPabrik, PenempatanGudang
    q = (select(m.id, m.peran).select_from(Perusahaan)
         .join(s, s.company_id == Perusahaan.id)
         .join(w, and_(w.lokasi_pabrik_id == s.id, w.company_id == Perusahaan.id))
         .join(Warehouse, Warehouse.id == w.warehouse_id)
         .join(m, and_(m.company_id == Perusahaan.id, m.user_id == user_id))
         .join(User, User.id == m.user_id)
         .where(Perusahaan.id == company_id, s.id == lokasi_pabrik_id,
                w.warehouse_id == warehouse_id, Perusahaan.aktif.is_(True),
                s.aktif.is_(True), m.aktif.is_(True), Warehouse.aktif.is_(True),
                func.lower(User.status) == 'aktif'))
    # Pemeriksaan konteks tidak boleh menyimpan draf ORM milik pemanggil.
    with db.no_autoflush:
        row = (await db.execute(q)).one_or_none()
    if row is None or not P.sah(row.peran):
        raise OrganisasiTidakDiizinkan(pesan)
    return KonteksKerja(user_id, company_id, lokasi_pabrik_id, warehouse_id,
                       row.id, P.normal(row.peran))
