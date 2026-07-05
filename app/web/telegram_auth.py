"""Validasi Telegram Mini App `initData` (login lewat Telegram).

Saat Mini App dibuka dari bot, Telegram menaruh `initData` — string query yang
DITANDATANGANI dengan token bot (HMAC-SHA256). Backend memvalidasi tanda tangan
itu untuk memastikan identitas user ASLI dari Telegram (tak bisa dipalsukan tanpa
token bot). Karena satu Mini App bisa dibuka dari >1 bot, kita coba SETIAP token
bot yang dikonfigurasi; cocok dengan salah satu = sah.

Referensi resmi: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


@dataclass
class InitData:
    """Hasil initData yang sudah tervalidasi."""

    telegram_user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    auth_date: int
    raw: dict  # seluruh field mentah (sudah terdekode)


def _valid_for_token(fields: dict, received_hash: str, bot_token: str) -> bool:
    """True bila tanda tangan `fields` cocok untuk `bot_token`."""
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, received_hash)


def validate_init_data(
    init_data: str, bot_tokens: list[str], *, max_age_seconds: int = 86_400
) -> InitData | None:
    """Validasi `initData`. Kembalikan InitData bila sah, else None.

    - Tanda tangan harus cocok untuk salah satu `bot_tokens`.
    - `auth_date` tak boleh lebih tua dari `max_age_seconds` (anti-replay).
    """
    if not init_data or not bot_tokens:
        return None
    try:
        fields = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received_hash = fields.pop("hash", None)
    if not received_hash or "auth_date" not in fields:
        return None

    # Kesegaran (anti-replay). auth_date = epoch detik.
    try:
        auth_date = int(fields["auth_date"])
    except ValueError:
        return None
    if max_age_seconds and (time.time() - auth_date) > max_age_seconds:
        return None

    # Tanda tangan cocok untuk salah satu token bot?
    if not any(_valid_for_token(fields, received_hash, t) for t in bot_tokens if t):
        return None

    # Ekstrak user (field 'user' = JSON string).
    user_raw = fields.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
        uid = int(user["id"])
    except (ValueError, KeyError, TypeError):
        return None

    return InitData(
        telegram_user_id=uid,
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        username=user.get("username"),
        auth_date=auth_date,
        raw=fields,
    )
