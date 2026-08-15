"""Poller AUTO-WATCH INVOICE (Phase 1) — pantau _TRANSIT → usul (arsip + update IT).

Tiap ~30 menit: pindai folder _TRANSIT untuk PDF baru, ekstrak (Haiku; teks PDF via
pypdf = gratis), dan bila LANGGANAN → ajukan gerbang gabungan (persetujuan_poller yang
kirim ✅/❌). Read-only sampai pemilik menyetujui.

PENGAMAN BIAYA: di balik flag `settings.invoice_auto` (default OFF); batas `_CAP` file per
putaran; dedup via pending aktif (tak mengusulkan file yang sama dua kali). Lampiran email
= increment berikutnya.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.kantor import invoice
from app.kantor.models import AksiPending

log = logging.getLogger("invoice.poller")

_TICK = 300
_INTERVAL = 30 * 60   # 30 menit
_CAP = 5              # maks file per putaran (jaga biaya)


async def _sudah_diusulkan(file_id: str) -> bool:
    """True bila sudah ada pending 'invoice_proses' AKTIF untuk file ini (anti-dobel)."""
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AksiPending.payload).where(
                AksiPending.jenis == "invoice_proses",
                AksiPending.status == "pending",
            ))).scalars().all()
    return any(file_id in (p or "") for p in rows)


async def _scan_sekali() -> int:
    from app.kantor.drive.client import DriveClient, terkonfigurasi
    from app.kantor.drive.operasi import transit_id
    if not terkonfigurasi():
        return 0
    c = DriveClient()
    tid = await asyncio.to_thread(transit_id, c)
    if not tid:
        log.warning("Folder _TRANSIT tak ditemukan — auto-watch dilewati.")
        return 0
    files = await asyncio.to_thread(c.anak, tid)
    kandidat = [f for f in files if f.mime == "application/pdf"][:_CAP]
    diusulkan = 0
    for f in kandidat:
        if await _sudah_diusulkan(f.id):
            continue
        try:
            aid = await invoice.usul_dari_file(f.id, f.mime, f.nama, asal_id=tid)
        except Exception:  # noqa: BLE001
            log.warning("proses invoice gagal: %s", f.nama, exc_info=True)
            continue
        if aid:
            diusulkan += 1
            log.info("Usul invoice #%s diajukan: %s", aid, f.nama)
    return diusulkan


async def run_invoice_poller(bots: dict[str, Bot]) -> None:
    if not settings.invoice_auto:
        log.info("Auto-watch invoice NONAKTIF (invoice_auto=false).")
        return
    from app.kantor.drive.client import terkonfigurasi
    if not terkonfigurasi():
        log.warning("Drive belum terkonfigurasi — auto-watch invoice NONAKTIF.")
        return
    log.info("Auto-watch invoice AKTIF (_TRANSIT tiap %s menit, maks %s/putaran).",
             _INTERVAL // 60, _CAP)
    terakhir: datetime | None = None
    while True:
        await asyncio.sleep(_TICK)
        try:
            now = datetime.now(timezone.utc)
            if terakhir is not None and (now - terakhir).total_seconds() < _INTERVAL:
                continue
            terakhir = now
            n = await _scan_sekali()
            if n:
                log.info("Auto-watch invoice: %s usulan diajukan.", n)
        except Exception:  # noqa: BLE001
            log.exception("Loop auto-watch invoice gagal (lanjut)")
