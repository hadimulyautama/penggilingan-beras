"""Manajemen pengguna (registrasi/aktivasi) — dikelola admin.

Dua cara mendaftar:
1. Telegram ID  -> langsung aktif.
2. Nomor HP     -> pra-daftar (status 'pending'); pengguna mengaktifkan
   sendiri dengan membagikan kontak Telegram-nya (nomor HP dicocokkan).
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Warehouse

#: Tangga peran sejak 3 September 2026. "staff" tidak lagi ditawarkan,
#: tetapi baris lama yang menyebutnya tetap sah dibaca — lihat
#: `bots.common.PERAN_UANG`.
_ROLES = {"operator", "admin", "superadmin"}


class UserAdminError(Exception):
    """Kesalahan manajemen user dengan pesan siap-tampil (args[0])."""


def norm_phone(s: str | None) -> str | None:
    """Normalkan nomor HP Indonesia ke bentuk kanonik '62xxxxxxxxxx'."""
    if not s:
        return None
    d = re.sub(r"\D", "", s)
    if not d:
        return None
    if d.startswith("0"):
        d = "62" + d[1:]
    elif d.startswith("8"):
        d = "62" + d
    return d


def _role_label(role: str) -> str:
    return {"operator": "Operator", "admin": "Direksi",
            "superadmin": "Super Admin", "staff": "Staff (lama)"}.get(role, role)


async def _warehouse_for_gudang(db: AsyncSession, gudang: int | None) -> Warehouse | None:
    if gudang == 2:
        like = "Gudang 2%"
    else:
        like = "Gudang 1%"  # default operator -> Gudang 1
    return (
        await db.execute(select(Warehouse).where(Warehouse.nama_gudang.like(like)))
    ).scalars().first()


async def register_user(
    db: AsyncSession, *, actor, nama: str | None, role: str | None,
    gudang: int | None, telegram_id: int | None, no_hp: str | None,
    lewat_sandi: bool = False,
) -> str:
    """Daftarkan pengguna baru. Kembalikan pesan konfirmasi siap-tampil.

    `lewat_sandi` menandai orang yang akan masuk lewat **webapp**, dengan nama
    pengguna dan sandi — bukan lewat Telegram.

    Kenapa itu mengubah aturannya: syarat "sebutkan Telegram ID atau nomor HP"
    lahir dari keterbatasan bot, yang tidak punya cara lain mengenali siapa
    yang sedang bicara. Webapp punya — kredensialnya sendiri. Memaksa Telegram
    ID untuk orang yang tak akan pernah memakai Telegram justru melanggengkan
    ikatan yang sedang dilepas Fase B, dan mendorong orang mengarang angka.
    """
    if not actor or actor.role != "admin":
        raise UserAdminError("⛔ Hanya admin yang bisa mendaftarkan pengguna.")
    if not nama:
        raise UserAdminError("Sebutkan nama pengguna. Contoh: `daftarkan operator Budi id 12345678 gudang 1`")
    role = (role or "").lower()
    if role not in _ROLES:
        raise UserAdminError("Peran harus: *operator*, *staff*, atau *admin*.")
    phone = norm_phone(no_hp)
    if not telegram_id and not phone and not lewat_sandi:
        raise UserAdminError(
            "Sebutkan *Telegram ID* atau *nomor HP*-nya.\n"
            "Contoh: `daftarkan operator Budi id 12345678 gudang 1`\n"
            "atau `daftarkan operator Budi hp 081234567890 gudang 1`"
        )

    if telegram_id:
        dup = (
            await db.execute(select(User).where(User.telegram_user_id == telegram_id))
        ).scalars().first()
        if dup:
            raise UserAdminError(f"Telegram ID {telegram_id} sudah terdaftar atas nama {dup.nama}.")
    if phone:
        dup = (
            await db.execute(select(User).where(User.whatsapp_number == phone))
        ).scalars().first()
        if dup:
            raise UserAdminError(f"Nomor HP {phone} sudah terdaftar atas nama {dup.nama}.")

    wh = await _warehouse_for_gudang(db, gudang) if role == "operator" else None
    # "pending" berarti menunggu orangnya membuktikan diri lewat Telegram.
    # Yang masuk lewat sandi tidak punya penantian itu — ia aktif begitu
    # kredensialnya dibuatkan, dan tanpa kredensial ia tak bisa masuk sama
    # sekali. Menandainya "pending" hanya akan membuatnya tak muncul di daftar
    # orang yang belum punya akun, sehingga akunnya tak pernah bisa dibuat.
    status = "aktif" if (telegram_id or lewat_sandi) else "pending"
    db.add(
        User(
            nama=nama,
            role=role,
            telegram_user_id=telegram_id,
            whatsapp_number=phone,
            default_warehouse_id=wh.id if wh else None,
            access_level="full" if role in {"admin", "staff"} else "operational",
            status=status,
        )
    )
    await db.commit()

    tempat = f" {wh.nama_gudang}" if wh else ""
    if status == "aktif" and lewat_sandi and not telegram_id:
        return (f"{nama} terdaftar sebagai {_role_label(role)}{tempat}. "
                "Sekarang buatkan akunnya di daftar di bawah.")
    if status == "aktif":
        return f"✓ {nama} terdaftar sebagai *{_role_label(role)}*{tempat} — langsung aktif (ID {telegram_id})."
    return (
        f"✓ {nama} terdaftar sebagai *{_role_label(role)}*{tempat} via HP {phone}.\n"
        "Status *menunggu aktivasi*: minta {nama} mengirim pesan ke bot lalu tekan "
        "tombol *📱 Bagikan Nomor HP* — akun otomatis aktif."
    ).replace("{nama}", nama)


async def list_users(db: AsyncSession) -> str:
    users = (
        await db.execute(select(User).order_by(User.role, User.nama))
    ).scalars().all()
    if not users:
        return "Belum ada pengguna terdaftar."
    lines = [f"👥 Pengguna terdaftar ({len(users)}):"]
    for u in users:
        ident = f"ID {u.telegram_user_id}" if u.telegram_user_id else (
            f"HP {u.whatsapp_number}" if u.whatsapp_number else "—")
        flag = "" if u.status == "aktif" else f" ⏳{u.status}"
        lines.append(f"• {u.nama} — {_role_label(u.role)} ({ident}){flag}")
    return "\n".join(lines)


async def set_user_status(db: AsyncSession, *, actor, ref: str | None, aktif: bool) -> str:
    if not actor or actor.role != "admin":
        raise UserAdminError("⛔ Hanya admin yang bisa mengubah status pengguna.")
    if not ref:
        raise UserAdminError("Sebutkan nama atau ID pengguna.")
    q = select(User)
    if ref.isdigit():
        q = q.where(User.telegram_user_id == int(ref))
    else:
        q = q.where(func.lower(User.nama).like(f"%{ref.lower()}%"))
    found = (await db.execute(q)).scalars().all()
    if not found:
        raise UserAdminError(f"Pengguna '{ref}' tidak ditemukan.")
    if len(found) > 1:
        nama = ", ".join(u.nama for u in found[:10])
        raise UserAdminError(f"Lebih dari satu cocok: {nama}. Sebutkan lebih spesifik / pakai ID.")
    u = found[0]
    if u.id == actor.id and not aktif:
        raise UserAdminError("Tidak bisa menonaktifkan akun Anda sendiri.")
    u.status = "aktif" if aktif else "nonaktif"
    await db.commit()
    return f"✓ {u.nama} kini *{u.status}*."


async def link_by_contact(
    db: AsyncSession, *, telegram_id: int, phone: str | None, nama: str | None
) -> User | None:
    """Aktifkan user pra-daftar via kontak: cocokkan nomor HP -> isi telegram_id."""
    p = norm_phone(phone)
    if not p:
        return None
    # Cocokkan pada 9 digit terakhir agar tahan beda prefix.
    tail = p[-9:]
    cand = (
        await db.execute(
            select(User).where(
                User.telegram_user_id.is_(None),
                User.whatsapp_number.isnot(None),
            )
        )
    ).scalars().all()
    match = next((u for u in cand if (u.whatsapp_number or "")[-9:] == tail), None)
    if match is None:
        return None
    match.telegram_user_id = telegram_id
    match.status = "aktif"
    if nama and not match.nama:
        match.nama = nama
    await db.commit()
    return match
