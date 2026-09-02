"""Penolong yang dipakai semua modul aksi cepat.

Dipisahkan dari `miniapp.py` ketika aksi inventory pindah ke modulnya sendiri:
keduanya membutuhkan penolong yang sama, dan saling mengimpor akan melingkar.
Isinya sengaja tipis — hanya hal yang benar-benar dipakai lebih dari satu
modul, bukan tempat penampungan.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.models import User


def wajib(cond: bool, msg: str = "Aksi ini tidak tersedia untuk peran Anda.") -> None:
    """Hentikan permintaan bila peran pemakai tidak berhak.

    Hak akses ditentukan di SERVER, bukan dengan menyembunyikan tombol: menu
    yang disaring per peran itu kenyamanan, bukan pengamanan.
    """
    if not cond:
        raise HTTPException(status_code=403, detail=msg)


def rp(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".")


def kg(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".") + " kg"


def galat(e: Exception, default: str) -> HTTPException:
    """Ubah kesalahan layanan jadi 400 dengan pesan yang sudah siap dibaca.

    Layanan di aplikasi ini melemparkan kesalahan dengan pesan berbahasa
    manusia di `args[0]` — itulah yang naik ke layar. `default` hanya jaring
    pengaman untuk kesalahan yang tidak membawa pesan apa pun.
    """
    return HTTPException(400, str(e.args[0]) if e.args else default)


async def kabar_chat(user: User, text: str, bot_name: str = "gudang1") -> None:
    """Kirim konfirmasi aksi cepat ke chat Telegram user (best-effort).

    Header berisi penanda 'Aksi cepat' + nama pelaku + jam, agar jelas apa yang
    terakhir dilakukan lewat tombol (bukan chat) dan tidak terlupa.

    Akan hilang sendiri ketika bot pabrik dimatikan (tahap B5): pemakai yang
    masuk lewat peramban tidak punya `telegram_user_id`, dan `notify_user`
    memang tidak melakukan apa-apa untuk mereka.
    """
    from app.bots.notify import notify_user
    from app.database import now_local
    stamp = now_local().strftime("%d/%m %H:%M")
    header = f"📱 *Aksi cepat* · {user.nama} · {stamp}"
    # Kirim ke bot ASAL Mini App dibuka (chat yang sedang dilihat user); bila tak
    # diketahui, pakai bot domain aksi. notify_user tetap fallback ke bot lain.
    target = getattr(user, "_miniapp_bot", None) or bot_name
    await notify_user(user.telegram_user_id, f"{header}\n{text}", target)
