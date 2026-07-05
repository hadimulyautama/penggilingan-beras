"""Dependency FastAPI untuk Mini App: autentikasi via Telegram initData → User.

Konvensi header (standar Mini App): `Authorization: tma <initDataRaw>`.
"""
from __future__ import annotations

from fastapi import Header, HTTPException
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.web.telegram_auth import validate_init_data


def _extract_init_data(authorization: str | None) -> str | None:
    """Ambil initData dari header 'Authorization: tma <initData>'."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "tma":
        return parts[1].strip()
    return None


async def require_miniapp_user(authorization: str | None = Header(default=None)) -> User:
    """Validasi initData → User aktif. 401 bila gagal, 403 bila belum terdaftar."""
    init_data = _extract_init_data(authorization)
    tokens = list(settings.bot_tokens.values())
    parsed = validate_init_data(init_data or "", tokens)
    if parsed is None:
        raise HTTPException(status_code=401, detail="initData Telegram tidak valid.")
    async with SessionLocal() as db:
        user = (
            await db.execute(
                select(User).where(
                    User.telegram_user_id == parsed.telegram_user_id,
                    User.status == "aktif",
                )
            )
        ).scalars().first()
    if user is None:
        raise HTTPException(
            status_code=403,
            detail="Akun Telegram Anda belum terdaftar/aktif. Hubungi admin.",
        )
    return user
