"""Keamanan modul Timbangan: sandi, sesi cookie, dan penjaga peran (RBAC).

Tanpa dependensi tambahan — memakai `hashlib.scrypt` (KDF modern di pustaka
standar) dan cookie bertanda tangan HMAC-SHA256.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request

from app.timbangan.config import tsettings
from app.timbangan.models import ROLE_ADMIN, ROLE_PENGAWAS, TimbanganAkun

log = logging.getLogger("timbangan.security")

NAMA_COOKIE = "timbangan_sesi"

# Parameter scrypt: seimbang antara aman & ringan untuk server kecil.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


class ButuhLogin(Exception):
    """Belum login — pengguna diarahkan ke halaman masuk."""


class AksesDitolak(Exception):
    """Sudah login tetapi peran tidak mencukupi."""

    def __init__(self, pesan: str = "Halaman ini tidak tersedia untuk peran Anda."):
        super().__init__(pesan)
        self.pesan = pesan


# ─────────────────────────── Sandi ───────────────────────────

def hash_sandi(sandi: str) -> str:
    """Hash sandi → 'scrypt$n$r$p$salt$hash' (salt acak per pengguna)."""
    if not sandi or len(sandi) < 6:
        raise ValueError("Kata sandi minimal 6 karakter.")
    salt = secrets.token_bytes(16)
    kunci = hashlib.scrypt(
        sandi.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${kunci.hex()}"


def cek_sandi(sandi: str, tersimpan: str) -> bool:
    """Verifikasi sandi terhadap hash tersimpan (tahan timing attack)."""
    try:
        skema, n, r, p, salt_hex, hash_hex = (tersimpan or "").split("$")
        if skema != "scrypt":
            return False
        kunci = hashlib.scrypt(
            (sandi or "").encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(kunci.hex(), hash_hex)


# ─────────────────────────── Sesi ───────────────────────────

def _kunci() -> bytes:
    rahasia = tsettings.secret_key
    if not rahasia:
        # Cadangan: kunci acak per proses. Sesi hangus saat restart — cukup
        # aman, tetapi di produksi WAJIB set TIMBANGAN_SECRET_KEY.
        global _KUNCI_SEMENTARA
        try:
            return _KUNCI_SEMENTARA
        except NameError:
            _KUNCI_SEMENTARA = os.urandom(32)
            log.warning(
                "TIMBANGAN_SECRET_KEY belum diset — memakai kunci sementara; "
                "semua sesi login akan hangus setiap kali server restart."
            )
            return _KUNCI_SEMENTARA
    return hashlib.sha256(rahasia.encode()).digest()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def buat_token(akun_id: int, *, hari: int | None = None) -> str:
    """Token sesi bertanda tangan: <payload>.<signature>.

    Sesi berlaku sampai petugas menekan Keluar — tiap orang memakai
    perangkatnya sendiri, jadi membukanya lagi tidak boleh meminta login.
    Batas hari di sini hanya jaring pengaman, bukan pengusir harian.
    """
    kedaluwarsa = datetime.now(timezone.utc) + timedelta(
        days=hari or tsettings.sesi_hari
    )
    payload = _b64e(json.dumps(
        {"sub": int(akun_id), "exp": int(kedaluwarsa.timestamp())},
        separators=(",", ":"),
    ).encode())
    tanda = _b64e(hmac.new(_kunci(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{tanda}"


def baca_token(token: str | None) -> int | None:
    """Kembalikan akun_id bila token sah & belum kedaluwarsa."""
    if not token or "." not in token:
        return None
    payload, _, tanda = token.partition(".")
    harapan = _b64e(hmac.new(_kunci(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(tanda, harapan):
        return None
    try:
        data = json.loads(_b64d(payload))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return int(data["sub"])
    except (ValueError, KeyError, TypeError):
        return None


# ─────────────────────────── Dependency ───────────────────────────

async def akun_opsional(request: Request) -> TimbanganAkun | None:
    """Akun dari cookie sesi, atau None. Tidak pernah melempar error."""
    from sqlalchemy import select

    from app.timbangan.db import sesi_db

    akun_id = baca_token(request.cookies.get(NAMA_COOKIE))
    if akun_id is None:
        return None
    async with sesi_db() as db:
        akun = (
            await db.execute(
                select(TimbanganAkun).where(
                    TimbanganAkun.id == akun_id,
                    TimbanganAkun.status == "aktif",
                )
            )
        ).scalars().first()
    request.state.akun = akun
    return akun


async def butuh_akun(request: Request) -> TimbanganAkun:
    """Wajib login. Bila belum → diarahkan ke halaman masuk."""
    akun = await akun_opsional(request)
    if akun is None:
        raise ButuhLogin()
    return akun


async def butuh_pengawas(
    akun: TimbanganAkun = Depends(butuh_akun),
) -> TimbanganAkun:
    """Pengawas atau Admin."""
    if akun.role not in (ROLE_PENGAWAS, ROLE_ADMIN):
        raise AksesDitolak("Halaman ini hanya untuk Pengawas dan Admin.")
    return akun


async def butuh_admin(akun: TimbanganAkun = Depends(butuh_akun)) -> TimbanganAkun:
    """Admin / Management saja."""
    if akun.role != ROLE_ADMIN:
        raise AksesDitolak("Halaman ini hanya untuk Admin.")
    return akun
