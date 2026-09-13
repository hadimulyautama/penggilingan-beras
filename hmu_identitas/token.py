"""Token sesi bertanda tangan HMAC-SHA256: <payload>.<signature>.

Muatan: `sub` (nomor akun), `v` (versi token akun), `exp`, dan isian
tambahan milik aplikasi (mis. `p` sesi pendek di Meja, `b` "akun bersama"
di timbangan). Versi ikut di dalam token: menaikkannya di akun membuat semua
token lama berhenti berlaku seketika — itulah yang membuat keluar-semua,
ganti sandi, reset, dan penonaktifan benar-benar memutus (QA P-S-05, T-19).

Tiap aplikasi memakai KUNCI-nya sendiri (SECRET_KEY masing-masing); yang
dibagi adalah bentuk dan aturannya, bukan rahasianya.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

#: Batas atas nomor akun yang masuk akal; di luar ini dulu sampai ke basis
#: data apa adanya dan pulang sebagai galat asyncpg mentah (QA P-S-12).
MAKS_ID = 2 ** 31 - 1


def kunci_dari(rahasia: str) -> bytes:
    return hashlib.sha256(rahasia.encode()).digest()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def buat_token(kunci: bytes, *, akun_id: int, versi: int, umur_detik: int,
               ekstra: dict | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(seconds=int(umur_detik))
    muatan = {**(ekstra or {}), "sub": int(akun_id), "v": int(versi or 1),
              "exp": int(exp.timestamp())}
    payload = _b64e(json.dumps(muatan, separators=(",", ":")).encode())
    tanda = _b64e(hmac.new(kunci, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{tanda}"


def baca_token(kunci: bytes, token: str | None) -> dict | None:
    """{'akun_id', 'versi', 'exp', ...ekstra} bila sah & belum kedaluwarsa.

    **Tak pernah melempar.** Cookie datang dari luar, isinya bisa apa saja —
    termasuk huruf non-ASCII yang dulu menjatuhkan `compare_digest`. Token
    lama tanpa `v` dianggap versi 1: deploy tak boleh memutus semua orang.
    """
    if not token or "." not in token:
        return None
    try:
        payload, _, tanda = token.partition(".")
        harapan = _b64e(hmac.new(kunci, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(tanda, harapan):
            return None
        data = json.loads(_b64d(payload))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        akun_id = int(data["sub"])
        if not 0 < akun_id <= MAKS_ID:
            return None
        keluar = {k: v for k, v in data.items() if k not in ("sub", "v", "exp")}
        keluar.update(akun_id=akun_id, versi=int(data.get("v", 1) or 1), exp=int(data["exp"]))
        return keluar
    except (ValueError, KeyError, TypeError, UnicodeError, AttributeError):
        return None


def masih_berlaku(dibaca: dict | None, *, versi_akun: int) -> bool:
    """Token yang sudah dibaca masih sepadan dengan versi akunnya?"""
    return dibaca is not None and int(dibaca["versi"]) >= int(versi_akun or 1)
