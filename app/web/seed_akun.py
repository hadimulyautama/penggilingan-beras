"""Akun webapp PERTAMA — jalan sekali saat sistem disiapkan.

Masalah ayam-dan-telur: yang boleh membuat akun hanyalah Super Admin, dan ia
sendiri baru bisa masuk kalau akunnya sudah ada. Dipecahkan lewat env, bukan
lewat halaman pendaftaran terbuka: selama `ADMIN_SANDI_AWAL` terisi DAN belum
ada satu akun pun, dibuatkan akun untuk pemilik `ADMIN_TELEGRAM_ID`.

Tidak ada sandi yang pernah ditulis ke log. Sesudah bisa masuk, ganti sandinya
(memang dipaksa) lalu kosongkan lagi variabel itu di Railway.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import ProduksiAkun
from app.models.akun import mode_bawaan
from app.web.security import hash_sandi
from hmu_core import User

log = logging.getLogger("web.seed_akun")


async def seed_akun_awal() -> None:
    if not settings.admin_sandi_awal:
        return
    if not settings.admin_telegram_id:
        log.warning("ADMIN_SANDI_AWAL diisi tapi ADMIN_TELEGRAM_ID kosong — "
                    "akun awal tidak dibuat.")
        return
    async with SessionLocal() as db:
        sudah_ada = (await db.execute(select(func.count(ProduksiAkun.id)))).scalar_one()
        if sudah_ada:
            log.info("Akun webapp sudah ada (%s) — ADMIN_SANDI_AWAL diabaikan; "
                     "boleh dikosongkan dari environment.", sudah_ada)
            return
        orang = (await db.execute(
            select(User).where(User.telegram_user_id == settings.admin_telegram_id)
        )).scalars().first()
        if orang is None:
            log.warning("User dengan ADMIN_TELEGRAM_ID tidak ditemukan — "
                        "akun awal tidak dibuat.")
            return
        try:
            hash_ = hash_sandi(settings.admin_sandi_awal)
        except ValueError as e:
            log.warning("ADMIN_SANDI_AWAL ditolak: %s", e)
            return
        db.add(ProduksiAkun(
            user_id=orang.id,
            username=(settings.admin_username or "admin").strip().lower(),
            password_hash=hash_, mode_perangkat=mode_bawaan(orang.role),
            harus_ganti_sandi=True,
        ))
        await db.commit()
    log.info("Akun webapp pertama dibuat untuk %s — WAJIB ganti sandi saat "
             "pertama masuk, lalu kosongkan ADMIN_SANDI_AWAL.", orang.nama)
