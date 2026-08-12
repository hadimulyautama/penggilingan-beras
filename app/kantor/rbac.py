"""Scope-checker RBAC — SATU pintu keputusan izin (Tahap 1).

Aturan: izin = union grant dari semua role AKTIF yang dipegang user.
  - '*' = owner  → izin semua domain (direksi).
  - mode: none < read < write < owner.
`boleh(grants, domain, mode)` murni & mudah diuji. Versi `*_user` membaca DB.

Enforcement WAJIB di sini (kode), tak pernah hanya di prompt.
"""
from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor.models import KantorGrant, KantorUserRole
from app.kantor.rbac_seed import GRANTS as _SEED
from app.kantor.rbac_seed import ROLES as _ROLES_KATALOG

_TINGKAT = {"none": 0, "read": 1, "write": 2, "owner": 3}
_KODE_ROLE = {k for k, _, _ in _ROLES_KATALOG}


def role_valid(kode: str) -> bool:
    return kode in _KODE_ROLE


def _gabung(pasangan) -> dict[str, str]:
    """Union (domain→mode tertinggi) dari iterable (domain, mode)."""
    out: dict[str, str] = {}
    for domain, mode in pasangan:
        if _TINGKAT.get(mode, 0) > _TINGKAT.get(out.get(domain, "none"), 0):
            out[domain] = mode
    return out


def boleh(grants: dict[str, str], domain: str, mode: str = "read") -> bool:
    """True bila union-grant mengizinkan `mode` pada `domain`. '*'=owner → semua."""
    perlu = _TINGKAT.get(mode, 1)
    if _TINGKAT.get(grants.get("*", "none"), 0) >= perlu:
        return True
    return _TINGKAT.get(grants.get(domain, "none"), 0) >= perlu


def grants_dari_seed(roles: set[str]) -> dict[str, str]:
    """Union grant dari POLICY in-memory (rbac_seed) — untuk uji & pratinjau,
    tanpa DB. Sumber kebenaran runtime tetap tabel `kantor_grant`."""
    return _gabung(
        (dom, mode) for r in roles for dom, mode in _SEED.get(r, {}).items()
    )


async def roles_user(user_id: int) -> set[str]:
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(KantorUserRole.role_kode).where(
                    KantorUserRole.user_id == user_id,
                    KantorUserRole.status == "aktif",
                )
            )
        ).scalars().all()
    return set(rows)


async def grants_user(user_id: int) -> dict[str, str]:
    roles = await roles_user(user_id)
    if not roles:
        return {}
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(KantorGrant.domain, KantorGrant.mode).where(
                    KantorGrant.role_kode.in_(roles)
                )
            )
        ).all()
    return _gabung(rows)


async def boleh_user(user_id: int, domain: str, mode: str = "read") -> bool:
    return boleh(await grants_user(user_id), domain, mode)


# ─────────────────── Onboarding: penugasan user↔role ───────────────────
async def tetapkan_role(user_id: int, role_kode: str, atasan_user_id: int | None = None) -> None:
    """Beri (atau aktifkan kembali) sebuah role ke user. `atasan_user_id` = penyetuju
    aksi berdampak untuk hat ini (rute persetujuan berjenjang)."""
    if not role_valid(role_kode):
        raise ValueError(f"role tak dikenal: {role_kode}")
    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(KantorUserRole).where(
                    KantorUserRole.user_id == user_id,
                    KantorUserRole.role_kode == role_kode,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            s.add(KantorUserRole(user_id=user_id, role_kode=role_kode,
                                 atasan_user_id=atasan_user_id, status="aktif"))
        else:
            row.status = "aktif"
            row.atasan_user_id = atasan_user_id
        await s.commit()


async def cabut_role(user_id: int, role_kode: str) -> None:
    """Cabut akses seketika (deprovisioning) — nonaktifkan baris, tak dihapus."""
    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(KantorUserRole).where(
                    KantorUserRole.user_id == user_id,
                    KantorUserRole.role_kode == role_kode,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.status = "nonaktif"
            await s.commit()


async def daftar_role_user(user_id: int) -> list[str]:
    """Role AKTIF yang dipegang user (untuk verifikasi/tampilan)."""
    return sorted(await roles_user(user_id))
