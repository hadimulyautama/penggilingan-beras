"""Sandi: scrypt dari pustaka standar, format 'scrypt$n$r$p$salt$hash'.

Formatnya SAMA dengan yang dipakai produksi dan timbangan sejak awal —
sengaja, supaya hash lama tetap cocok tanpa dibentuk ulang saat akun
disatukan.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_N, _R, _P = 2 ** 14, 8, 1
MIN_PANJANG = 6


def hash_sandi(sandi: str) -> str:
    if not sandi or len(sandi) < MIN_PANJANG:
        raise ValueError(f"Kata sandi minimal {MIN_PANJANG} karakter.")
    salt = secrets.token_bytes(16)
    kunci = hashlib.scrypt(sandi.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${kunci.hex()}"


def cek_sandi(sandi: str | None, tersimpan: str | None) -> bool:
    """Tahan timing attack; hash yang rusak/kosong tak pernah cocok."""
    try:
        skema, n, r, p, salt_hex, hash_hex = (tersimpan or "").split("$")
        if skema != "scrypt":
            return False
        kunci = hashlib.scrypt(
            (sandi or "").encode(), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(kunci.hex(), hash_hex)


#: Hash yang TIDAK pernah cocok — dipakai saat nama penggunanya tak dikenal,
#: supaya waktu jawab nama-ada dan nama-tak-ada sama (QA P-S-13).
HASH_TIRUAN = hash_sandi(secrets.token_urlsafe(24))


async def cek_sandi_async(sandi: str | None, tersimpan: str | None) -> bool:
    """scrypt ~50 ms CPU — di threadpool, supaya tak menahan event loop (QA P-S-04)."""
    import asyncio

    return await asyncio.to_thread(cek_sandi, sandi, tersimpan)


def sandi_acak(panjang: int = 10) -> str:
    """Sandi awal yang mudah dibacakan lewat telepon — tanpa huruf/angka rancu."""
    abjad = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(abjad) for _ in range(panjang))
