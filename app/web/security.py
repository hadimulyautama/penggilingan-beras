"""Keamanan webapp produksi: sandi, sesi cookie, dan penjaga peran.

Tanpa dependensi tambahan — `hashlib.scrypt` dari pustaka standar dan cookie
bertanda tangan HMAC-SHA256. Polanya menyalin `app/timbangan/security.py` di
repo timbangan yang sudah berjalan di pos timbang; disamakan dengan sengaja
supaya orang yang memperbaiki salah satunya langsung paham yang lain.

Perbedaannya satu: peran TIDAK disimpan pada akun. Ia dibaca dari `users` lewat
relasi, sehingga tak mungkin berbeda antara master dan webapp.
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
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import ProduksiAkun

log = logging.getLogger("web.security")

NAMA_COOKIE = "produksi_sesi"

#: Daftar nama pengguna yang PERNAH masuk di perangkat ini — bukan rahasia,
#: bukan token. Gunanya menghapus pengetikan berulang di perangkat gudang:
#: operator memilih namanya lalu hanya mengetik sandi. Isinya sengaja cuma
#: nama pengguna, dan hanya dibaca server saat merender halaman masuk.
COOKIE_PERANGKAT = "produksi_perangkat"
MAKS_NAMA_PERANGKAT = 4

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


def sandi_acak(panjang: int = 10) -> str:
    """Sandi awal yang mudah dibacakan lewat telepon — tanpa huruf/angka rancu."""
    abjad = "abcdefghjkmnpqrstuvwxyz23456789"  # tanpa i l o 0 1
    return "".join(secrets.choice(abjad) for _ in range(panjang))


# ─────────────────────────── Sesi ───────────────────────────

_KUNCI_SEMENTARA: bytes | None = None


def _kunci() -> bytes:
    rahasia = settings.secret_key
    if not rahasia:
        # Cadangan: kunci acak per proses. Sesi hangus saat restart — cukup
        # aman, tetapi di produksi WAJIB set SECRET_KEY.
        global _KUNCI_SEMENTARA
        if _KUNCI_SEMENTARA is None:
            _KUNCI_SEMENTARA = os.urandom(32)
            log.warning(
                "SECRET_KEY belum diset — memakai kunci sementara; semua sesi "
                "login akan hangus setiap kali server restart."
            )
        return _KUNCI_SEMENTARA
    return hashlib.sha256(rahasia.encode()).digest()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def umur_sesi_detik(akun: ProduksiAkun) -> int:
    """Umur sesi menurut jenis perangkat.

    HP pribadi: panjang — membuka aplikasi lagi tidak boleh meminta sandi,
    karena pencatatan terjadi sambil berdiri di dekat mesin dan setiap
    hambatan kecil berujung pencatatan yang ditunda lalu dikarang.

    Perangkat bersama: pendek — supaya pekerjaan tidak tercatat atas nama
    orang yang memakainya sebelum Anda.
    """
    if akun.sesi_pendek:
        return settings.sesi_bersama_menit * 60
    return settings.sesi_hari * 24 * 3600


def buat_token(akun: ProduksiAkun) -> str:
    """Token sesi bertanda tangan: <payload>.<signature>."""
    kedaluwarsa = datetime.now(timezone.utc) + timedelta(
        seconds=umur_sesi_detik(akun)
    )
    payload = _b64e(json.dumps(
        {"sub": int(akun.id), "exp": int(kedaluwarsa.timestamp())},
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

async def akun_opsional(request: Request) -> ProduksiAkun | None:
    """Akun dari cookie sesi, atau None. Tidak pernah melempar error."""
    akun_id = baca_token(request.cookies.get(NAMA_COOKIE))
    if akun_id is None:
        return None
    async with SessionLocal() as db:
        akun = (
            await db.execute(
                select(ProduksiAkun).where(
                    ProduksiAkun.id == akun_id,
                    ProduksiAkun.status == "aktif",
                )
            )
        ).scalars().first()
        if akun is not None:
            # Peran ikut termuat (relasi lazy="joined") sebelum sesi ditutup.
            _ = akun.peran
    request.state.akun = akun
    return akun


async def butuh_akun(request: Request) -> ProduksiAkun:
    """Wajib login. Bila belum → diarahkan ke halaman masuk."""
    akun = await akun_opsional(request)
    if akun is None:
        raise ButuhLogin()
    return akun


async def butuh_staff(akun: ProduksiAkun = Depends(butuh_akun)) -> ProduksiAkun:
    """Staff kantor & Direksi — batas yang sama dengan `can_see_financials`."""
    if not akun.is_staff:
        raise AksesDitolak("Halaman ini hanya untuk staff kantor.")
    return akun


async def butuh_admin(akun: ProduksiAkun = Depends(butuh_akun)) -> ProduksiAkun:
    """Direksi saja."""
    if not akun.is_admin:
        raise AksesDitolak("Halaman ini hanya untuk Direksi.")
    return akun


def baca_nama_perangkat(nilai: str | None) -> list[str]:
    """Nama pengguna yang tercatat pernah masuk di perangkat ini."""
    if not nilai:
        return []
    keluar: list[str] = []
    for bagian in nilai.split(","):
        nama = bagian.strip().lower()
        # Saring ketat: isi cookie datang dari peramban, jadi tak pernah
        # dipercaya sebagai apa pun selain kandidat nama pengguna.
        if nama and nama.isascii() and nama.replace("_", "").replace("-", "").isalnum():
            if nama not in keluar:
                keluar.append(nama)
    return keluar[:MAKS_NAMA_PERANGKAT]


def tulis_nama_perangkat(nilai: str | None, username: str) -> str:
    """Taruh `username` di depan daftar perangkat, buang duplikat."""
    daftar = [username] + [n for n in baca_nama_perangkat(nilai) if n != username]
    return ",".join(daftar[:MAKS_NAMA_PERANGKAT])


async def ada_akun() -> bool:
    """True bila sudah ada akun webapp — dipakai untuk pengaturan awal."""
    from sqlalchemy import func

    async with SessionLocal() as db:
        return bool((await db.execute(
            select(func.count(ProduksiAkun.id))
        )).scalar_one())
