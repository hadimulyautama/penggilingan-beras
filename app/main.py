"""Entrypoint: FastAPI + 3 Telegram bot (long-polling) dalam satu proses."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.bots.registry import build_bots, run_polling
from app.config import settings
from app.database import SessionLocal
from app.services.dashboard import dashboard_data, render_dashboard_html
from app.services.billing_poller import run_billing_poller
from app.services.briefing_poller import run_briefing_poller
from app.services.deadline_poller import run_deadline_poller
from app.services.email_rapi_poller import run_email_rapi_poller
from app.services.heartbeat import run_heartbeat
from app.services.persetujuan_poller import run_persetujuan_poller
from app.services.scheduler import run_late_drying_scheduler
from app.services.seed import seed_master
from app.web.miniapp import router as miniapp_router

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
    from app.bots.notify import set_bots
    set_bots(bots)
    poll_task = asyncio.create_task(run_polling(built))
    sched_task = asyncio.create_task(run_late_drying_scheduler(bots))
    pers_task = asyncio.create_task(run_persetujuan_poller(bots))
    rapi_task = asyncio.create_task(run_email_rapi_poller(bots))  # pilah+rapi+lapor
    brief_task = asyncio.create_task(run_briefing_poller(bots))
    deadline_task = asyncio.create_task(run_deadline_poller(bots))
    billing_task = asyncio.create_task(run_billing_poller(bots))
    hb_task = asyncio.create_task(run_heartbeat(bots))
    log.info("Backend siap. Bot aktif: %s", list(settings.bot_tokens.keys()) or "(none)")
    try:
        yield
    finally:
        # Hentikan task latar dengan membatalkan, lalu tutup sesi bot.
        # Guard karena saat --reload polling bisa belum/selesai berjalan.
        for task in (poll_task, sched_task, pers_task, brief_task,
                     deadline_task, billing_task, rapi_task, hb_task):
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
app.include_router(miniapp_router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": settings.claude_model,
        "bots": list(settings.bot_tokens.keys()),
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(token: str = Query("")) -> HTMLResponse:
    """Dashboard produksi staff (web). Dilindungi token rahasia di URL.

    Set env `DASHBOARD_TOKEN` lalu buka /dashboard?token=<token>. Berisi data
    uang (HPP) — hanya bagikan link ke staff/admin.
    """
    if not settings.dashboard_token:
        raise HTTPException(status_code=404, detail="Dashboard web tidak aktif.")
    if token != settings.dashboard_token:
        raise HTTPException(status_code=403, detail="Token tidak valid.")
    async with SessionLocal() as db:
        data = await dashboard_data(db)
    return HTMLResponse(render_dashboard_html(data))
