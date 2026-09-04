"""Seed data master idempoten — dijalankan saat startup.

Membuat DB kosong (mis. environment staging baru atau DB produksi baru)
langsung siap pakai: gudang, silo, mesin pengering, dan user admin.
Aman dijalankan berulang: hanya menambah yang belum ada.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Brand,
    Dryer,
    PackageSize,
    PackagingMaterial,
    RiceQualityStandard,
    Silo,
    User,
    Warehouse,
)

log = logging.getLogger("app.seed")

_WAREHOUSES = ["Gudang 1 - Selepan", "Gudang 2 - Penyosohan"]
# (nama_gudang, nama_silo, kapasitas_ton)
_SILOS = [
    ("Gudang 1 - Selepan", "Silo A", 35),
    ("Gudang 1 - Selepan", "Silo B", 35),
    ("Gudang 2 - Penyosohan", "Silo A", None),
    ("Gudang 2 - Penyosohan", "Silo B", None),
]


async def seed_master() -> None:
    async with SessionLocal() as db:
        created: list[str] = []

        # Gudang
        for nama in _WAREHOUSES:
            exists = (
                await db.execute(select(Warehouse).where(Warehouse.nama_gudang == nama))
            ).scalars().first()
            if not exists:
                db.add(Warehouse(nama_gudang=nama))
                created.append(f"gudang '{nama}'")
        await db.flush()

        # Silo (per gudang)
        for wnama, snama, cap in _SILOS:
            w = (
                await db.execute(select(Warehouse).where(Warehouse.nama_gudang == wnama))
            ).scalars().first()
            if not w:
                continue
            ex = (
                await db.execute(
                    select(Silo).where(Silo.warehouse_id == w.id, Silo.nama_silo == snama)
                )
            ).scalars().first()
            if not ex:
                db.add(Silo(warehouse_id=w.id, nama_silo=snama, kapasitas_ton=cap))
                created.append(f"{snama} {wnama}")

        # Mesin pengering Gudang 1 (migrasi 0003 no-op di DB kosong).
        g1 = (
            await db.execute(
                select(Warehouse).where(Warehouse.nama_gudang.like("Gudang 1%"))
            )
        ).scalars().first()
        if g1:
            d = (
                await db.execute(select(Dryer).where(Dryer.warehouse_id == g1.id))
            ).scalars().first()
            if not d:
                db.add(
                    Dryer(
                        # 30 ton di atas kertas, dengan toleransi 3 ton
                        # (`settings.dryer_toleransi_kg`) — jadi yang benar-
                        # benar ditolak adalah di atas 33 ton.
                        #
                        # Toleransinya bukan kelonggaran pencatatan melainkan
                        # kenyataan mesin: muatan sedikit di atas angka kertas
                        # masih kering merata, dan menolak truk yang sudah
                        # berdiri di halaman karena selisih setengah ton hanya
                        # memindahkan masalahnya ke tumpukan.
                        #
                        # Berbeda dari silo dan tumpukan yang memang tak
                        # berbatas: dryer adalah mesin.
                        warehouse_id=g1.id, nama="Pengering 1",
                        kapasitas_kg=30000, status="aktif",
                    )
                )
                created.append("mesin pengering G1")

        # User admin awal dari environment (opsional).
        if settings.admin_telegram_id:
            u = (
                await db.execute(
                    select(User).where(
                        User.telegram_user_id == settings.admin_telegram_id
                    )
                )
            ).scalars().first()
            if not u:
                db.add(
                    User(
                        nama=settings.admin_name,
                        role="admin",
                        access_level="full",
                        telegram_user_id=settings.admin_telegram_id,
                        status="aktif",
                    )
                )
                created.append(f"admin '{settings.admin_name}'")

        # ── Master inventory: standar mutu, merk, jenis karung, ukuran ──
        _STANDARDS = [
            ("sayur", "Sayur", 1), ("medium", "Medium", 2),
            ("medsuper", "MedSuper", 3), ("premium", "Premium", 4),
        ]
        for kode, nama, urut in _STANDARDS:
            ada = (
                await db.execute(select(RiceQualityStandard).where(RiceQualityStandard.kode == kode))
            ).scalars().first()
            if not ada:
                db.add(RiceQualityStandard(kode=kode, nama=nama, urutan=urut))
                created.append(f"standar {nama}")

        _BRANDS = [
            ("Imbiss", "house"), ("LosPulen", "house"), ("Pulenesia", "house"),
            ("Pulenisme", "house"), ("Raja", "house"), ("Lele", "house"),
            ("Melon", "house"), ("Polos", "polos"),
        ]
        for nama, tipe in _BRANDS:
            ada = (
                await db.execute(select(Brand).where(Brand.nama == nama))
            ).scalars().first()
            if not ada:
                db.add(Brand(nama=nama, tipe=tipe))
                created.append(f"merk {nama}")

        _MATERIALS = [
            ("biasa", "Karung biasa"), ("laminasi", "Karung laminasi"),
            ("putih", "Karung putih"), ("polos", "Karung polos"),
            ("bekas", "Karung bekas"), ("karung_pk", "Karung PK (reusable)"),
        ]
        for kode, nama in _MATERIALS:
            ada = (
                await db.execute(select(PackagingMaterial).where(PackagingMaterial.kode == kode))
            ).scalars().first()
            if not ada:
                db.add(PackagingMaterial(kode=kode, nama=nama))
                created.append(f"karung {nama}")

        for ukuran in (5, 10, 25, 48, 50):
            ada = (
                await db.execute(select(PackageSize).where(PackageSize.ukuran_kg == ukuran))
            ).scalars().first()
            if not ada:
                db.add(PackageSize(ukuran_kg=ukuran))
                created.append(f"ukuran {ukuran}kg")

        if created:
            await db.commit()
            log.info("Seed master: menambah %s", ", ".join(created))
        else:
            log.info("Seed master: semua data master sudah ada (no-op).")
