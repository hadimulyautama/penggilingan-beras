"""Seed katalog role + grant RBAC (Tahap 1). Idempoten (upsert).

Ini POLICY (role→domain→mode) — reusable & data-driven. Penugasan user↔role
(`kantor_user_role`) diisi saat ONBOARDING (butuh Telegram ID tiap orang), bukan
di sini.

Domain: hr, gaji, keuangan, arsip, legal, sengketa, folder_it, sekretaris,
marketing, penjualan, operasional, laporan, email, kalender, knowledge,
buat_dokumen. Sub-scope sensitif: gaji, sengketa, folder_it. 'pembayaran' TIDAK
ada grant agen (eksekusi di bank). '*' = semua domain (direksi).
Mode: none < read < write < owner.
"""
from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor.models import KantorGrant, KantorRole

ROLES: list[tuple[str, str, str]] = [
    ("pegawai", "Pegawai (base)", "Semua pengguna kantor: layanan bersama, dibatasi scope data."),
    ("direksi", "Direksi", "Akses penuh semua domain + approver tertinggi."),
    ("komisaris", "Komisaris", "Oversight read-only: laporan + knowledge umum; tak lihat brankas."),
    ("hr_manager", "HR Manager", "Domain HR + gaji."),
    ("office_manager", "Office Manager", "Keuangan/arsip/sekretaris/marketing/penjualan; gaji & folder IT (read)."),
    ("legal_officer", "Legal Officer", "Legal + sengketa."),
    ("staff_hr", "Staff HR", "Administrasi HR (presensi/cuti), TANPA gaji."),
    ("staff_legal", "Staff Legal", "Legal & sengketa (read)."),
    ("staff_ops", "Staff Operasional", "Operasional, penjualan, arsip, sekretaris (write)."),
    ("operator", "Operator", "Input + edit/revert/hapus entry SENDIRI, gudang sendiri (minimal)."),
    ("it_manager", "IT Manager", "Folder IT (owner). Kosong dulu."),
]

GRANTS: dict[str, dict[str, str]] = {
    "pegawai": {"email": "write", "kalender": "write", "buat_dokumen": "write",
                "arsip": "write", "knowledge": "read"},
    "direksi": {"*": "owner"},
    "komisaris": {"laporan": "read", "knowledge": "read"},
    "hr_manager": {"hr": "owner", "gaji": "owner"},
    "office_manager": {"keuangan": "owner", "gaji": "read", "arsip": "owner",
                       "sekretaris": "owner", "marketing": "owner", "penjualan": "owner",
                       "folder_it": "read"},
    "legal_officer": {"legal": "owner", "sengketa": "write"},
    "staff_hr": {"hr": "write"},
    "staff_legal": {"legal": "read", "sengketa": "read"},
    "staff_ops": {"operasional": "write", "penjualan": "write", "arsip": "write",
                  "sekretaris": "write"},
    "operator": {"operasional": "write"},
    "it_manager": {"folder_it": "owner"},
}


async def seed() -> tuple[int, int]:
    async with SessionLocal() as s:
        for kode, nama, ket in ROLES:
            row = (
                await s.execute(select(KantorRole).where(KantorRole.kode == kode))
            ).scalar_one_or_none()
            if row is None:
                s.add(KantorRole(kode=kode, nama=nama, keterangan=ket))
            else:
                row.nama, row.keterangan = nama, ket
        for role_kode, doms in GRANTS.items():
            for domain, mode in doms.items():
                row = (
                    await s.execute(
                        select(KantorGrant).where(
                            KantorGrant.role_kode == role_kode,
                            KantorGrant.domain == domain,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    s.add(KantorGrant(role_kode=role_kode, domain=domain, mode=mode))
                else:
                    row.mode = mode
        await s.commit()
    return len(ROLES), sum(len(d) for d in GRANTS.values())
