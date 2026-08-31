"""Briefing PAGI proaktif → Telegram pemilik.

07:00 WIB, Senin–Sabtu (Minggu libur), sekali per hari. Isi:
  • Email penting semalam (3 mailbox terkelola, ~15 jam terakhir)
  • Agenda & jatuh tempo (kalender, hari ini + 7 hari ke depan)
  • Ringkasan operasional pabrik (dari dashboard_data)

Read-only; kirim ke settings.admin_telegram_id. Tiap bagian dibungkus try/except
agar satu sumber gagal tak menggagalkan seluruh brief. Jalan di service
`penggilingan-beras`. State "sudah terkirim hari ini" di memori (cukup — kalau
restart & masih jam 7–8 akan kirim, dedupe per tanggal).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot

from app.config import settings
from app.database import SessionLocal
from app.kantor import mail_gmail

log = logging.getLogger("brief.poller")

_TICK = 300  # cek tiap 5 menit
_WIB = timezone(timedelta(hours=7))
_JAM_KIRIM = 7          # 07:00 WIB
_JENDELA_JAM = 9        # toleransi kirim s/d <09:00 (mis. bila server baru bangun)
_BATAS_TG = 3800        # potong pesan agar aman dari limit Telegram (~4096)


def _num(x) -> str:
    try:
        return f"{float(x):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(x)


async def _bagian_email() -> str:
    blok = []
    for mb in mail_gmail.daftar_mailbox():
        try:
            out = await asyncio.to_thread(
                mail_gmail.daftar, mb, "in:inbox newer_than:15h", 5)
        except Exception:  # noqa: BLE001
            continue
        if out and not out.startswith("📭"):
            blok.append(out.split("\nUntuk isi lengkap")[0])
    return "\n\n".join(blok) if blok else "— tak ada email baru semalam. 👍"


async def _bagian_agenda() -> str:
    from app.kantor.drive import operasi
    hari = datetime.now(_WIB).date()
    try:
        return await asyncio.to_thread(
            operasi.lihat_agenda, hari.isoformat(),
            (hari + timedelta(days=7)).isoformat())
    except Exception:  # noqa: BLE001
        log.warning("agenda gagal", exc_info=True)
        return "— agenda tak tersedia saat ini."


async def _bagian_operasional() -> str:
    from app.services.dashboard import dashboard_data
    try:
        async with SessionLocal() as db:
            d = await dashboard_data(db)
        o = d.get("operasional", {}) or {}
        g = o.get("gabah_hari_ini", {}) or {}
        silo = o.get("silo", []) or []
        terisi = sum(1 for s in silo if s.get("terisi"))
        pk = o.get("stok_pk", {}) or {}
        return (
            f"• Gabah masuk hari ini: {g.get('batch', 0)} batch, "
            f"{_num(g.get('total_kg', 0))} kg\n"
            f"• Pengeringan berjalan: {len(o.get('pengeringan', []) or [])} lot\n"
            f"• Silo terisi: {terisi}/{len(silo)}\n"
            f"• Giling berjalan: {len(o.get('giling', []) or [])} proses\n"
            f"• Stok beras jadi (PK): {_num(pk.get('total', 0))} kg"
        )
    except Exception:  # noqa: BLE001
        log.warning("operasional gagal", exc_info=True)
        return "— data operasional tak tersedia saat ini."


def _hitung_rapi_sync() -> int:
    total = 0
    for mb in mail_gmail.daftar_mailbox():
        try:
            r = mail_gmail._svc(mb).users().messages().list(
                userId="me", q=f"label:{mail_gmail._LABEL_AUTORAPI} newer_than:1d",
                maxResults=100).execute()
            total += len(r.get("messages", []))
        except Exception:  # noqa: BLE001
            continue
    return total


async def _bagian_rapi() -> str:
    try:
        n = await asyncio.to_thread(_hitung_rapi_sync)
    except Exception:  # noqa: BLE001
        return ""
    if not n:
        return ""
    return (f"🤫 Dirapikan otomatis (24 jam): {n} email rutin diarsipkan. "
            "('kembalikan email yang tadi diarsip' untuk undo.)")


async def susun_brief() -> str:
    now = datetime.now(_WIB)
    email, agenda, ops, rapi = await asyncio.gather(
        _bagian_email(), _bagian_agenda(), _bagian_operasional(), _bagian_rapi())
    hari_id = now.strftime("%d-%m-%Y")
    teks = (
        f"☀️ Selamat pagi! Briefing {hari_id}\n\n"
        f"📬 EMAIL SEMALAM\n{email}\n\n"
        f"📅 AGENDA & JATUH TEMPO (7 hari ke depan)\n{agenda}\n\n"
        f"🏭 OPERASIONAL\n{ops}"
    )
    if rapi:
        teks += f"\n\n{rapi}"
    return teks


def _potong(teks: str) -> list[str]:
    if len(teks) <= _BATAS_TG:
        return [teks]
    bagian, buf = [], ""
    for baris in teks.split("\n"):
        if len(buf) + len(baris) + 1 > _BATAS_TG:
            bagian.append(buf)
            buf = ""
        buf += baris + "\n"
    if buf.strip():
        bagian.append(buf)
    return bagian


async def run_briefing_poller(bots: dict[str, Bot]) -> None:
    bot = bots.get("kantor")
    if bot is None or not settings.admin_telegram_id:
        log.warning("Briefing pagi NONAKTIF (bot 'kantor'/ADMIN_TELEGRAM_ID kosong).")
        return
    log.info("Briefing pagi aktif (07:00 WIB, Sen–Sab → pemilik %s)",
             settings.admin_telegram_id)
    terkirim: date | None = None
    while True:
        await asyncio.sleep(_TICK)
        try:
            now = datetime.now(_WIB)
            if now.weekday() == 6:            # Minggu libur
                continue
            if not (_JAM_KIRIM <= now.hour < _JENDELA_JAM):
                continue
            if terkirim == now.date():         # sudah kirim hari ini
                continue
            teks = await susun_brief()
            terkirim = now.date()
            for bagian in _potong(teks):
                await bot.send_message(settings.admin_telegram_id, bagian)
            log.info("Briefing pagi terkirim (%s)", now.date())
        except Exception:  # noqa: BLE001
            log.exception("Loop briefing pagi gagal (lanjut)")
