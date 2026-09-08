"""Siapa pemakai endpoint aksi.

Dulu ada dua jalan masuk: sesi webapp, dan `initData` bertanda tangan token bot
untuk yang membuka Mini App dari Telegram. Jalan kedua dibubarkan bersama bot
produksi — tanpa bot, tak ada yang bisa menghasilkan initData yang sah, jadi
mempertahankan kodenya cuma menyimpan pintu yang tak punya kunci maupun tamu.

Sekarang satu jalan: sesi Pos Produksi. Operasional dan timbangan memang
dicatat di aplikasinya, bukan lewat percakapan.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.models import User


async def pengguna_aksi(request: Request) -> User:
    """Pemakai endpoint aksi — dari sesi Pos Produksi."""
    from app.web.security import akun_opsional

    akun = await akun_opsional(request)
    if akun is not None and akun.user is not None:
        return akun.user
    raise HTTPException(
        status_code=401,
        detail="Sesi Anda berakhir. Muat ulang halaman dan masuk kembali.",
    )
