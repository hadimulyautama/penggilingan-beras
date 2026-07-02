"""Seed data awal — idempotent. Jalankan: python -m app.seed

Membuat 2 gudang, 4 silo (A/B per gudang), dan 1 user admin.
Gunakan variabel lingkungan opsional untuk admin:
  SEED_ADMIN_NAMA, SEED_ADMIN_TELEGRAM_ID, SEED_ADMIN_WA
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Dryer, Silo, User, Warehouse


async def seed() -> None:
    async with SessionLocal() as db:
        # ── Gudang ──
        result = await db.execute(select(Warehouse))
        existing = {w.nama_gudang: w for w in result.scalars().all()}

        g1 = existing.get("Gudang 1 - Selepan")
        if not g1:
            g1 = Warehouse(
                nama_gudang="Gudang 1 - Selepan",
                alamat=None,
                kapasitas_tumpuk_ton=None,
                kapasitas_tumpuk_pk_ton=30,
            )
            db.add(g1)

        g2 = existing.get("Gudang 2 - Penyosohan")
        if not g2:
            g2 = Warehouse(
                nama_gudang="Gudang 2 - Penyosohan",
                alamat=None,
                kapasitas_tumpuk_ton=60,
                kapasitas_tumpuk_pk_ton=60,
            )
            db.add(g2)

        await db.flush()  # dapatkan id gudang

        # ── Silo A & B per gudang ──
        result = await db.execute(select(Silo))
        existing_silos = {(s.warehouse_id, s.nama_silo) for s in result.scalars().all()}
        for wh in (g1, g2):
            # Silo Gudang 1: 35 ton per silo. Gudang 2 (kolam campuran) belum diatur.
            kapasitas = 35 if wh is g1 else None
            for nama in ("Silo A", "Silo B"):
                if (wh.id, nama) not in existing_silos:
                    db.add(Silo(warehouse_id=wh.id, nama_silo=nama, kapasitas_ton=kapasitas))

        # ── Mesin pengering Gudang 1 (1 unit, 35 ton) ──
        result = await db.execute(select(Dryer).where(Dryer.warehouse_id == g1.id))
        if not result.scalars().first():
            db.add(Dryer(warehouse_id=g1.id, nama="Pengering 1", kapasitas_kg=35000))

        # ── Admin user ──
        admin_tg = os.getenv("SEED_ADMIN_TELEGRAM_ID")
        admin_wa = os.getenv("SEED_ADMIN_WA")
        admin_nama = os.getenv("SEED_ADMIN_NAMA", "Admin")
        result = await db.execute(select(User).where(User.role == "admin"))
        admin = result.scalars().first()
        if not admin:
            db.add(
                User(
                    nama=admin_nama,
                    role="admin",
                    telegram_user_id=int(admin_tg) if admin_tg else None,
                    whatsapp_number=admin_wa,
                    default_warehouse_id=g1.id,
                    access_level="full",
                )
            )
        elif admin_tg and admin.telegram_user_id is None:
            # Backfill Telegram ID pada admin yang sudah ada (bootstrap akses).
            admin.telegram_user_id = int(admin_tg)
            print(f"  ↳ telegram_user_id admin di-set ke {admin_tg}")

        await db.commit()
        print("✓ Seed selesai: 2 gudang, silo A/B per gudang, 1 admin.")
        if not admin_tg:
            print(
                "  ⚠ Admin belum punya telegram_user_id. Set SEED_ADMIN_TELEGRAM_ID "
                "lalu jalankan ulang, atau daftarkan via /daftar di bot."
            )


if __name__ == "__main__":
    asyncio.run(seed())
