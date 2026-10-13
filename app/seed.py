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

        g1 = next((w for w in existing.values() if w.kode_fungsi == "g1"), None) or existing.get("Gudang 1 - Selepan")
        if not g1:
            g1 = Warehouse(
                kode_fungsi="g1",
                nama_gudang="Gudang 1 - Selepan",
                alamat=None,
                kapasitas_tumpuk_ton=None,
                kapasitas_tumpuk_pk_ton=30,
            )
            db.add(g1)
        g1.kode_fungsi = "g1"

        g2 = next((w for w in existing.values() if w.kode_fungsi == "g2"), None) or existing.get("Gudang 2 - Penyosohan")
        if not g2:
            g2 = Warehouse(
                kode_fungsi="g2",
                nama_gudang="Gudang 2 - Penyosohan",
                alamat=None,
                kapasitas_tumpuk_ton=60,
                kapasitas_tumpuk_pk_ton=60,
            )
            db.add(g2)
        g2.kode_fungsi = "g2"

        await db.flush()  # dapatkan id gudang

        # ── Silo per gudang ──
        result = await db.execute(select(Silo))
        existing_silos = {(s.warehouse_id, s.nama_silo) for s in result.scalars().all()}
        for wh in (g1, g2):
            # Gudang 1 memiliki tiga silo gabah @35 ton. Silo Gudang 2
            # menerima bahan campuran; jenis isi historis bukan pembatas.
            kapasitas = 35 if wh is g1 else None
            nama_silo = ("Silo A", "Silo B", "Silo C") if wh is g1 else ("Silo A", "Silo B")
            for nama in nama_silo:
                if (wh.id, nama) not in existing_silos:
                    db.add(Silo(
                        warehouse_id=wh.id,
                        nama_silo=nama,
                        kapasitas_ton=kapasitas,
                        jenis_isi="gabah" if wh is g1 else "campuran",
                        komoditas_diizinkan=(
                            ["gabah_kering"] if wh is g1
                            else ["pk", "beras_putih", "reject", "broken", "menir"]
                        ),
                    ))
            if wh is g1:
                for silo in (await db.execute(select(Silo).where(Silo.warehouse_id == wh.id))).scalars():
                    if silo.jenis_isi != "gabah":
                        silo.jenis_isi = "gabah"

        # ── Mesin pengering Gudang 1 (1 unit, 35 ton) ──
        result = await db.execute(select(Dryer).where(Dryer.warehouse_id == g1.id))
        if not result.scalars().first():
            db.add(Dryer(warehouse_id=g1.id, nama="Pengering 1", kapasitas_kg=35000))

        # ── Admin user ──
        admin_tg = os.getenv("SEED_ADMIN_TELEGRAM_ID")
        admin_wa = os.getenv("SEED_ADMIN_WA")
        admin_nama = os.getenv("SEED_ADMIN_NAMA", "Admin")
        # Super Admin ikut dihitung: pabrik yang adminnya sudah dinaikkan akan
        # dianggap belum punya admin sama sekali, lalu diberi akun kedua yang
        # tak diminta siapa pun.
        from app.peran import PERAN_ADMIN_KEATAS

        result = await db.execute(
            select(User).where(User.role.in_(PERAN_ADMIN_KEATAS)))
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
