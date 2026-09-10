"""RUNNER onboarding RBAC — ISI telegram_id tiap orang, lalu jalankan.

Cara dapat ID: orang chat bot sekali → bot balas "belum terdaftar. ID: 12345"
(jalur ini deterministik, TIDAK butuh API Anthropic — cukup bot ter-DEPLOY).

Jalankan (butuh DB publik, TIDAK butuh API):
  cd <repo>; PYTHONPATH=. DATABASE_URL=<DATABASE_PUBLIC_URL> .venv/bin/python \
    /path/ke/kantor-onboarding-runner.py

Idempoten — aman dijalankan berkali-kali. Modul: app/kantor/rbac_onboard.py.
"""
import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor import rbac, rbac_onboard
from app.models.master import User

# ISI angka telegram_id tiap orang. Biarkan None yang belum dapat ID.
BINDINGS: dict[str, int | None] = {
    "wahid": None,
    "miftah": None,
    "muthia": None,
    "elfira": None,
    "kurniawan": None,
    "eka": None,
    "nurhadi": None,
    "ninik": None,
    "isnaini": None,
}


async def main():
    aktif = {k: v for k, v in BINDINGS.items() if v}
    if not aktif:
        print("Belum ada telegram_id diisi. Edit BINDINGS dulu.")
        return
    for line in await rbac_onboard.onboard(aktif):
        print(line)
    print("--- verifikasi role aktif ---")
    async with SessionLocal() as s:
        for k, tg in aktif.items():
            u = (await s.execute(select(User).where(User.telegram_user_id == tg))).scalar_one_or_none()
            if u:
                print(f"  {k} → {await rbac.daftar_role_user(u.id)}")


asyncio.run(main())
