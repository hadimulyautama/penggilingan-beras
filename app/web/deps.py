"""Siapa yang memanggil endpoint aksi — dua jalur, satu hasil.

Endpoint aksi (`app/web/miniapp.py`) ditulis untuk Mini App Telegram dan
mengenali pemakainya dari `initData` yang ditandatangani token bot. Fase B
menambahkan jalur kedua: sesi cookie webapp.

Sejak 3 September 2026 jalur Telegram TERTUTUP BAGI OPERATOR. Bot gudang 1 dan
gudang 2 dihapus, dan seandainya seorang operator masih memegang Mini App lama,
ia ditolak di sini — bukan dibiarkan lewat pintu yang sudah dinyatakan tutup.

Alasannya bukan sekadar merapikan: perangkat gudang dipakai bergantian,
sedangkan akun Telegram menempel pada orang. Selama kedua jalur hidup
berdampingan, catatan bisa tertulis atas nama pemilik ponsel, bukan atas nama
yang sedang bekerja.

Staff dan Direksi masih memakai bot admin, jadi jalur initData tetap ada untuk
mereka.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Request
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


async def pengguna_aksi(
    request: Request, authorization: str | None = Header(default=None)
) -> User:
    """Pemakai endpoint aksi: sesi webapp lebih dulu, initData untuk staff."""
    from app.web.security import akun_opsional

    akun = await akun_opsional(request)
    if akun is not None and akun.user is not None:
        return akun.user

    pengguna = await require_miniapp_user(authorization)
    if pengguna.role == "operator":
        # Ditolak dengan menunjuk jalan, bukan sekadar ditutup: yang membuka
        # Mini App lama tidak tahu bahwa jalurnya sudah dipensiunkan.
        raise HTTPException(
            status_code=403,
            detail=("Operator mencatat lewat Pos Produksi di peramban, bukan "
                    "lewat Telegram. Buka alamat Pos Produksi dan masuk "
                    "dengan nama pengguna Anda."),
        )
    return pengguna


async def require_miniapp_user(authorization: str | None = Header(default=None)) -> User:
    """Validasi initData → User aktif. 401 bila gagal, 403 bila belum terdaftar."""
    init_data = _extract_init_data(authorization)
    parsed = validate_init_data(init_data or "", settings.bot_tokens)
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
    # Bot ASAL Mini App dibuka → konfirmasi aksi cepat dikirim ke chat itu
    # (bukan chat bot lain), agar feedback muncul di layar yang sedang dilihat.
    user._miniapp_bot = parsed.bot_name
    return user
