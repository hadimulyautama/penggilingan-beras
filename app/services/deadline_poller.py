"""RADAR JATUH TEMPO proaktif → Telegram pemilik (Fase 2).

Tiap hari 07:00 WIB, gabung tenggat dari 2 sumber:
  1. Google Calendar (primary) — acara berpenanda 🔔 atau kata kunci tenggat
     (renewal/jatuh tempo/pajak/bayar/kontrak/perpanjang/expire/kadaluarsa).
  2. IT Accounts sheet, tab Services, kolom "Tgl Renewal" (parse tanggal Indonesia).

Kirim HANYA bila ada tenggat yang menyentuh jenjang H-7 / H-3 / H-1 / H-0 (atau baru
TERLEWAT ≤3 hari). Kebanyakan hari: diam. Read-only. Dedupe harian (in-memory date).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot

from app.config import settings

log = logging.getLogger("deadline.poller")

_TICK = 300
_WIB = timezone(timedelta(hours=7))
_JAM_KIRIM, _JENDELA = 7, 9
_SHEET_ID = os.getenv("IT_ACCOUNTS_SHEET_ID",
                      "1BxcGg1GitQmjTwbKRHmXUdiU2c2Z1yXt9TGK7kIOLY0")
_HORIZON = 31  # hari ke depan yang dipindai

_KATA = ("🔔", "renewal", "jatuh tempo", "jatuh-tempo", "tempo", "pajak", "bayar",
         "kontrak", "perpanjang", "expire", "kadaluarsa", "kedaluwarsa", "deadline")
_BULAN = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "jun": 6, "jul": 7,
          "agu": 8, "ags": 8, "agt": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10,
          "nov": 11, "des": 12, "dec": 12}
_RE_TGL = re.compile(r"(\d{1,2})\s*([A-Za-z]{3,})\s*(\d{4})")


def _parse_tgl_id(teks: str) -> date | None:
    m = _RE_TGL.search(teks or "")
    if not m:
        return None
    d, bln, th = m.groups()
    bulan = _BULAN.get(bln[:3].lower())
    if not bulan:
        return None
    try:
        return date(int(th), bulan, int(d))
    except ValueError:
        return None


def _tenggat_kalender() -> list[tuple[date, str]]:
    from app.kantor.drive.client import DriveClient, terkonfigurasi
    if not terkonfigurasi():
        return []
    c = DriveClient()
    now = datetime.now(_WIB)
    acara = c.kalender_acara(now.isoformat(),
                             (now + timedelta(days=_HORIZON)).isoformat(),
                             cal_id="primary", maks=50)
    out = []
    for a in acara:
        judul = a.get("ringkasan", "")
        if not any(k in judul.lower() for k in _KATA):
            continue
        try:
            d = date.fromisoformat((a.get("mulai", "") or "")[:10])
        except ValueError:
            continue
        out.append((d, judul.replace("🔔", "").strip()))
    return out


def _tenggat_sheet() -> list[tuple[date, str]]:
    from app.kantor.drive.client import DriveClient, terkonfigurasi
    if not terkonfigurasi():
        return []
    c = DriveClient()
    r = c._sheets().spreadsheets().values().get(
        spreadsheetId=_SHEET_ID, range="Services!A2:L300").execute()
    out = []
    for row in r.get("values", []):
        if len(row) < 11:
            continue
        d = _parse_tgl_id(row[10])  # kolom "Tgl Renewal"
        if d:
            out.append((d, f"Renewal {row[1]}"))  # kolom "Service / Platform"
    return out


# jenjang: (hari_selisih yang memicu) → (urutan, label)
_JENJANG = {
    -3: (0, "⚠️ TERLEWAT"), -2: (0, "⚠️ TERLEWAT"), -1: (0, "⚠️ TERLEWAT"),
    0: (1, "🔴 HARI INI"), 1: (2, "🟠 BESOK (H-1)"),
    3: (3, "🟡 3 HARI LAGI"), 7: (4, "🔵 7 HARI LAGI"),
}
_ID_BULAN = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep",
             "Okt", "Nov", "Des"]


def susun_radar() -> str:
    hari = datetime.now(_WIB).date()
    kal = _tenggat_kalender()
    tgl_kal = {d for d, _ in kal}
    # kalender = sumber utama; sheet hanya tambah tanggal yang BELUM ada di kalender
    sheet = [(d, n) for d, n in _tenggat_sheet() if d not in tgl_kal]
    seen, tenggat = set(), []
    for d, nama in kal + sheet:
        kunci = (d, nama.lower()[:12])
        if kunci in seen:
            continue
        seen.add(kunci)
        tenggat.append((d, nama))

    grup: dict[int, tuple[str, list[str]]] = {}
    for d, nama in tenggat:
        selisih = (d - hari).days
        j = _JENJANG.get(selisih)
        if not j:
            continue
        urut, label = j
        tgl_str = f"{d.day} {_ID_BULAN[d.month]}"
        grup.setdefault(urut, (label, []))
        grup[urut][1].append(f"• {nama} — {tgl_str}")
    if not grup:
        return ""
    blok = []
    for urut in sorted(grup):
        label, items = grup[urut]
        blok.append(label + ":\n" + "\n".join(items))
    return "⏰ Radar Jatuh Tempo\n\n" + "\n\n".join(blok)


async def run_deadline_poller(bots: dict[str, Bot]) -> None:
    import asyncio
    bot = bots.get("kantor")
    if bot is None or not settings.admin_telegram_id:
        log.warning("Radar jatuh tempo NONAKTIF (bot 'kantor'/ADMIN_TELEGRAM_ID kosong).")
        return
    log.info("Radar jatuh tempo aktif (07:00 WIB tiap hari → pemilik %s)",
             settings.admin_telegram_id)
    terkirim: date | None = None
    while True:
        await asyncio.sleep(_TICK)
        try:
            now = datetime.now(_WIB)
            if not (_JAM_KIRIM <= now.hour < _JENDELA) or terkirim == now.date():
                continue
            teks = await asyncio.to_thread(susun_radar)
            terkirim = now.date()
            if teks:
                await bot.send_message(settings.admin_telegram_id, teks)
                log.info("Radar jatuh tempo terkirim (%s)", now.date())
        except Exception:  # noqa: BLE001
            log.exception("Loop radar jatuh tempo gagal (lanjut)")
