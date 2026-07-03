"""Entrypoint: FastAPI + 3 Telegram bot (long-polling) dalam satu proses."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bots.registry import build_bots, run_polling
from app.config import settings
from app.services.scheduler import run_late_drying_scheduler
from app.services.seed import seed_master

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pastikan data master ada (penting untuk DB kosong: staging / DB baru).
    try:
        await seed_master()
    except Exception:
        log.exception("Seed master gagal (lanjut jalan)")
    built = build_bots()
    app.state.bots = built
    bots = {name: bot for name, bot, _dp in built}
    poll_task = asyncio.create_task(run_polling(built))
    sched_task = asyncio.create_task(run_late_drying_scheduler(bots))
    log.info("Backend siap. Bot aktif: %s", list(settings.bot_tokens.keys()) or "(none)")
    try:
        yield
    finally:
        # Hentikan task latar dengan membatalkan, lalu tutup sesi bot.
        # Guard karena saat --reload polling bisa belum/selesai berjalan.
        for task in (poll_task, sched_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Error saat menghentikan task latar")
        for _, bot, _dp in built:
            try:
                await bot.session.close()
            except Exception:
                pass


app = FastAPI(title="Sistem Penggilingan Beras — Backend", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": settings.claude_model,
        "bots": list(settings.bot_tokens.keys()),
    }
