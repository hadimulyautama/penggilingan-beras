"""SATU fungsi "boleh masuk?" — dan saudara-saudaranya — untuk semua aplikasi.

  · `periksa_kredensial(db, username, sandi)` — pintu masuk dengan sandi.
  · `akun_aktif(db, akun_id, versi)` — pintu tiap PERMINTAAN dari sesi:
    akun ada, akun aktif, orangnya aktif di `users`, versi token sepadan.
  · `naikkan_versi`, `ganti_sandi`, `nonaktifkan` — tindakan yang HARUS
    memutus sesi, dan di sini memang memutusnya.
  · `ada_superadmin_aktif` — jaring pengaman "tak ada Super Admin".

Pembatas percobaan (per nama + alamat) sengaja TIDAK di sini: ia butuh
keadaan per proses dan tiap aplikasi sudah punya `gerbang_masuk`-nya.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_core import User

from . import peran as P
from . import sandi as S
from .model import AKTIF, NONAKTIF, Akun

PESAN_SALAH = "Nama pengguna atau kata sandi salah."
PESAN_NONAKTIF = "Akun ini sedang dinonaktifkan. Hubungi Super Admin."


class Tolak(Exception):
    """Ditolak, dengan kode HTTP yang pantas dan pesan siap tampil."""

    def __init__(self, kode: int, pesan: str):
        super().__init__(pesan)
        self.kode, self.pesan = kode, pesan


def normal_username(username: str | None) -> str:
    return (username or "").strip().lower()


async def periksa_kredensial(db: AsyncSession, username: str, sandi: str) -> Akun:
    """Akun yang cocok — atau `Tolak` 401 (salah) / 403 (nonaktif).

    Nama yang tak ada dan sandi yang salah dijawab dengan pesan DAN waktu
    yang sama: hash tiruan tetap dihitung supaya selisih waktunya tak
    membocorkan daftar nama pengguna (QA P-S-13).
    """
    uname = normal_username(username)
    akun = (await db.execute(select(Akun).where(Akun.username == uname))).scalars().first()
    cocok = await S.cek_sandi_async(sandi, akun.password_hash if akun else S.HASH_TIRUAN)
    if akun is None or not cocok:
        raise Tolak(401, PESAN_SALAH)
    if not akun.aktif:
        raise Tolak(403, PESAN_NONAKTIF)
    return akun


async def catat_login(db: AsyncSession, akun: Akun) -> None:
    akun.terakhir_login = datetime.now(timezone.utc)
    await db.commit()


async def akun_aktif(db: AsyncSession, akun_id: int, versi: int) -> Akun | None:
    """Akun untuk sesi ini — atau None bila sesinya tak boleh berlanjut.

    Tiga pemeriksaan, tiap permintaan: akun ada & aktif, orangnya aktif di
    master (`users.status` — saklar yang berlaku untuk semua aplikasi, QA
    X-11), dan versi token tak lebih rendah dari versi akun (QA P-S-05).
    """
    if not akun_id or akun_id <= 0:
        return None
    akun = (await db.execute(select(Akun).where(Akun.id == int(akun_id)))).scalars().first()
    if akun is None or not akun.aktif:
        return None
    if int(versi or 1) < int(akun.token_version or 1):
        return None
    return akun


async def naikkan_versi(db: AsyncSession, akun_id: int) -> int:
    """Seluruh sesi akun ini berhenti berlaku. Mengembalikan versi baru."""
    await db.execute(update(Akun).where(Akun.id == akun_id)
                     .values(token_version=Akun.token_version + 1))
    await db.commit()
    return int((await db.execute(select(Akun.token_version).where(Akun.id == akun_id))).scalar_one())


async def ganti_sandi(db: AsyncSession, akun: Akun, *, sandi_lama: str | None,
                      sandi_baru: str, wajib_lama: bool = True) -> int:
    """Ganti sandi sendiri; sesi lama di semua perangkat putus. Mengembalikan
    versi baru supaya perangkat yang menggantinya bisa memasang token baru.

    `wajib_lama=False` hanya saat sandi masih sandi awal dari Super Admin:
    orangnya baru saja membuktikan dirinya di halaman masuk.
    """
    if wajib_lama and not await S.cek_sandi_async(sandi_lama, akun.password_hash):
        raise Tolak(400, "Kata sandi lama salah.")
    if await S.cek_sandi_async(sandi_baru, akun.password_hash):
        raise Tolak(400, "Kata sandi baru harus berbeda dari yang lama.")
    try:
        hash_baru = S.hash_sandi(sandi_baru)
    except ValueError as e:
        raise Tolak(400, str(e)) from None
    baris = await db.get(Akun, akun.id)
    baris.password_hash = hash_baru
    baris.harus_ganti_sandi = False
    baris.token_version = (baris.token_version or 1) + 1
    await db.commit()
    return int(baris.token_version)


async def ada_superadmin_aktif(db: AsyncSession, kecuali_akun_id: int | None = None) -> bool:
    q = (select(func.count(Akun.id)).join(User, User.id == Akun.user_id)
         .where(Akun.status == AKTIF, User.status == AKTIF, User.role == P.SUPERADMIN))
    if kecuali_akun_id is not None:
        q = q.where(Akun.id != kecuali_akun_id)
    return bool((await db.execute(q)).scalar_one())


async def nonaktifkan(db: AsyncSession, user_id: int, *, aktif: bool = False) -> None:
    """SATU saklar: `users.status` (dibaca semua aplikasi) + cermin di akun
    + versi token naik → akses putus pada permintaan berikutnya di mana pun.

    Menolak menonaktifkan Super Admin aktif terakhir: pabrik tanpa Super
    Admin tak bisa mengangkat siapa pun, dan jalan pulihnya lewat Postgres.
    """
    orang = await db.get(User, user_id)
    if orang is None:
        raise Tolak(404, "Orang tidak ditemukan.")
    akun = (await db.execute(select(Akun).where(Akun.user_id == user_id))).scalars().first()
    if not aktif and P.super_saja(orang.role) and not await ada_superadmin_aktif(
            db, kecuali_akun_id=akun.id if akun else None):
        raise Tolak(409, "Ini Super Admin aktif terakhir — angkat Super Admin lain dulu.")
    orang.status = AKTIF if aktif else NONAKTIF
    if akun is not None:
        akun.status = AKTIF if aktif else NONAKTIF
        if not aktif:
            akun.token_version = (akun.token_version or 1) + 1
    await db.commit()
