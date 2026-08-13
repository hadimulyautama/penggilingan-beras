"""Onboarding RBAC — rencana penugasan role per orang + fungsi eksekusi.

Cara pakai (saat bot live): tiap orang chat bot sekali → catat Telegram ID-nya
(lihat pesan "belum terdaftar" / /whoami). Isi `bindings = {key: telegram_id}`
lalu `await onboard(bindings)`. Idempoten (tetapkan_role = upsert; user upsert
by telegram_user_id).

RENCANA sudah sesuai keputusan pemilik (lihat memori kantor-org-rbac):
  key → (nama_lengkap, [role...], atasan_key | None)
Coarse role users: 'admin' utk Direksi (akses bot penuh), 'staff' selebihnya.
Operator TIDAK di sini (dikelola per gudang).
"""
from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor import rbac
from app.models.master import User

RENCANA: dict[str, tuple[str, list[str], str | None]] = {
    "wahid":     ("Ahmad Wahid Nurhani", ["direksi", "pegawai"], None),
    "miftah":    ("Ahmad Tsalits Miftah Nurhani", ["direksi", "pegawai"], None),
    "muthia":    ("Nurul Mutia Diansyah", ["hr_manager", "pegawai"], "wahid"),
    "elfira":    ("Elfira Geya Ananda",
                  ["office_manager", "staff_hr", "staff_legal", "pegawai"], "wahid"),
    "kurniawan": ("Kurniawan Setiadi", ["legal_officer", "pegawai"], "wahid"),
    "eka":       ("Eka Wahyu Nugrahani",
                  ["staff_ops", "staff_hr", "staff_legal", "pegawai"], "elfira"),
    "nurhadi":   ("Nurhadi", ["komisaris"], None),
    "ninik":     ("Ninik Mulyani", ["komisaris"], None),
    "isnaini":   ("Ahmad Isnaini Shidqi Nurhani", ["komisaris"], None),
}


def _coarse(roles: list[str]) -> str:
    return "admin" if "direksi" in roles else "staff"


async def onboard(bindings: dict[str, int]) -> list[str]:
    """bindings: {key: telegram_id}. Upsert user + tetapkan role sesuai RENCANA.
    Return laporan per orang."""
    laporan: list[str] = []
    key_uid: dict[str, int] = {}

    # 1) upsert users → kumpulkan key→user_id (dibutuhkan utk resolve atasan)
    async with SessionLocal() as s:
        for key, tg in bindings.items():
            if key not in RENCANA:
                laporan.append(f"! {key}: tak ada di RENCANA — dilewati")
                continue
            nama, roles, _ = RENCANA[key]
            coarse = _coarse(roles)
            u = (
                await s.execute(select(User).where(User.telegram_user_id == tg))
            ).scalar_one_or_none()
            if u is None:
                u = User(nama=nama, role=coarse, telegram_user_id=tg,
                         access_level=("full" if coarse == "admin" else "office"),
                         status="aktif")
                s.add(u)
                await s.flush()
            else:
                u.nama, u.role = nama, coarse
            key_uid[key] = u.id
        await s.commit()

    # 2) tetapkan kantor-role + atasan (rute persetujuan berjenjang)
    for key, uid in key_uid.items():
        nama, roles, atasan_key = RENCANA[key]
        atasan_uid = key_uid.get(atasan_key) if atasan_key else None
        for r in roles:
            await rbac.tetapkan_role(uid, r, atasan_user_id=atasan_uid)
        laporan.append(f"✓ {key} (uid={uid}) → {roles}  atasan={atasan_key or '-'}")
    return laporan
