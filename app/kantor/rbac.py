"""Scope-checker RBAC — SATU pintu keputusan izin (Tahap 1).

Aturan: izin = union grant dari semua role AKTIF yang dipegang user.
  - '*' = owner  → izin semua domain (direksi).
  - mode: none < read < write < owner.
`boleh(grants, domain, mode)` murni & mudah diuji. Versi `*_user` membaca DB.

Enforcement WAJIB di sini (kode), tak pernah hanya di prompt.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor import rbac_map
from app.kantor.models import KantorConfig, KantorGrant, KantorUserRole
from app.kantor.rbac_seed import GRANTS as _SEED
from app.kantor.rbac_seed import ROLES as _ROLES_KATALOG

log = logging.getLogger("kantor.rbac")

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


# ───────────────────── Enforcement (gate tiap tool) ─────────────────────
class AksesDitolak(Exception):
    """Aksi ditolak oleh RBAC."""


def pesan_tolak(domain: str, mode: str) -> str:
    return (f"⛔ Kamu tak punya akses ({mode}) ke area '{domain}'. "
            f"Hubungi Direksi bila memang perlu.")


# Tool sensitif → cara menentukan (domain, mode). Tool tak terdaftar = tak digate.
_EMAIL_READ = {"baca_email", "cari_email", "baca_email_isi"}
_EMAIL_WRITE = {"draft_email", "kirim_email", "arsip_email", "tandai_dibaca_email",
                "label_email", "batalkan_arsip_email"}
_GAJIHUB_READ = {"karyawan_gajihub", "cuti_gajihub", "pengajuan_gajihub"}
_GAJIHUB_WRITE = {"setujui_pengajuan", "tolak_pengajuan"}
_KLEDO_READ = {"tagihan_kledo", "faktur_kledo", "kontak_kledo", "akun_kledo", "neraca_kledo"}


def _domain_mode(name: str, args: dict) -> tuple[str, str] | None:
    """(domain, mode) yang dibutuhkan tool ini, atau None bila tak digate."""
    if name in _EMAIL_READ or name in _EMAIL_WRITE:
        d = rbac_map.domain_mailbox(args.get("mailbox", ""))
        if not d:
            return None  # mailbox tak dikenal → tak digate di sini
        return (d, "read" if name in _EMAIL_READ else "write")
    if name == "payroll_gajihub":
        return ("gaji", "read")
    if name in _GAJIHUB_READ:
        return ("hr", "read")
    if name in _GAJIHUB_WRITE:
        return ("hr", "write")
    if name in _KLEDO_READ:
        return ("keuangan", "read")
    return None


async def _mode_enforce() -> str:
    """'off' | 'shadow' | 'on'. Default 'shadow' (cek+log, belum menolak)."""
    try:
        async with SessionLocal() as s:
            nilai = (
                await s.execute(
                    select(KantorConfig.nilai).where(KantorConfig.kunci == "rbac_enforce")
                )
            ).scalar_one_or_none()
        return (nilai or "shadow").strip().lower()
    except Exception:
        return "shadow"


# Domain sensitif yang isinya bisa bocor lewat pencarian knowledge.
_DOMAIN_SENSITIF_KNOWLEDGE = {"gaji", "sengketa", "folder_it", "keuangan", "hr", "legal"}


def larang_knowledge(grants: dict[str, str]) -> set[str]:
    """Domain sensitif yang TAK boleh muncul di hasil pencarian knowledge untuk
    pemegang grant ini (yang tak punya izin baca domain tsb)."""
    return {d for d in _DOMAIN_SENSITIF_KNOWLEDGE if not boleh(grants, d, "read")}


async def knowledge_larang(user_id: int | None) -> set[str]:
    """Set domain yang harus dikecualikan dari knowledge untuk user. HANYA aktif
    saat enforce='on' (shadow/off → set kosong = tak menyaring)."""
    if await _mode_enforce() != "on":
        return set()
    grants = await grants_user(user_id) if user_id is not None else {}
    return larang_knowledge(grants)


async def cek_tool_akses(user_id: int | None, name: str, args: dict) -> str | None:
    """Gate satu pemanggilan tool. Return None bila boleh; pesan tolak (str) bila
    enforce='on' & ditolak. Shadow: log saja lalu izinkan (None). Off: tak cek."""
    flag = await _mode_enforce()
    if flag == "off":
        return None
    dm = _domain_mode(name, args or {})
    if dm is None:
        return None
    domain, mode = dm
    if user_id is not None and await boleh_user(user_id, domain, mode):
        return None
    log.warning("RBAC deny [%s] user=%s tool=%s domain=%s mode=%s",
                flag, user_id, name, domain, mode)
    if flag == "on":
        return pesan_tolak(domain, mode)
    return None  # shadow → izinkan (hanya tercatat)
