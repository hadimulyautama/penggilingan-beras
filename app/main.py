"""Entrypoint produksi: FastAPI + bot pabrik (long-polling) dalam satu proses.

Kantor AI TIDAK lagi dijalankan di sini — bot, poller proaktif, dan heartbeat-nya
pindah ke service & repo sendiri (github.com/hadimulyautama/kantor). Yang tersisa
untuk Kantor hanyalah API internal `/internal/produksi/*` (app/web/internal.py)
yang dipanggilnya untuk membaca data pabrik.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.bots.registry import build_bots, run_polling
from app.config import settings
from app.database import SessionLocal
from app.services.dashboard import dashboard_data, render_dashboard_html
from app.penggilingan.gudang1.services.sinkron_bobot import run_sinkron_bobot_poller
from app.services.scheduler import run_late_drying_scheduler
from app.services.seed import seed_master
from app.web.auth import router as auth_router
from app.web.internal import router as internal_router
from app.web.miniapp import router as miniapp_router
from app.web.pengguna import router as pengguna_router
from app.web.security import (
    AksesDitolak,
    ButuhLogin,
    NAMA_COOKIE,
    akun_opsional,
    buat_token,
    umur_sesi_detik,
)
from app.web.seed_akun import seed_akun_awal
from app.web.tampilan import render

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pastikan data master ada (penting untuk DB kosong: staging / DB baru).
    try:
        await seed_master()
    except Exception:
        log.exception("Seed master gagal (lanjut jalan)")
    try:
        await seed_akun_awal()
    except Exception:
        log.exception("Seed akun webapp gagal (lanjut jalan)")
    built = build_bots()
    app.state.bots = built
    bots = {name: bot for name, bot, _dp in built}
    from app.bots.notify import set_bots
    set_bots(bots)
    poll_task = asyncio.create_task(run_polling(built))
    sched_task = asyncio.create_task(run_late_drying_scheduler(bots))
    sinkron_task = asyncio.create_task(run_sinkron_bobot_poller(bots))
    log.info("Backend siap. Bot aktif: %s", list(settings.bot_tokens.keys()) or "(none)")
    try:
        yield
    finally:
        # Hentikan task latar dengan membatalkan, lalu tutup sesi bot.
        # Guard karena saat --reload polling bisa belum/selesai berjalan.
        for task in (poll_task, sched_task, sinkron_task):
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
app.include_router(internal_router)
app.include_router(auth_router)
app.include_router(pengguna_router)


# ── Sesi & penjaga halaman ──

@app.middleware("http")
async def perpanjang_sesi_pendek(request: Request, call_next):
    """Sesi perangkat gudang dihitung dari pemakaian TERAKHIR, bukan dari jam
    masuk: cookie-nya diperbarui setiap permintaan. Efeknya sesi mati sendiri
    setelah ditinggal menganggur — bukan memutus orang yang sedang bekerja."""
    balasan = await call_next(request)
    akun = getattr(request.state, "akun", None)
    if akun is not None and akun.sesi_pendek and balasan.status_code < 400:
        balasan.set_cookie(
            NAMA_COOKIE, buat_token(akun), max_age=umur_sesi_detik(akun),
            httponly=True, samesite="lax",
            secure=request.url.scheme == "https", path="/",
        )
    return balasan


@app.exception_handler(ButuhLogin)
async def _belum_masuk(request: Request, exc: ButuhLogin):
    from urllib.parse import quote
    return RedirectResponse(f"/masuk?next={quote(request.url.path)}", status_code=303)


@app.exception_handler(AksesDitolak)
async def _akses_ditolak(request: Request, exc: AksesDitolak):
    return render(request, "error.html", pesan=exc.pesan, status_code=403)


@app.get("/", response_class=HTMLResponse)
async def beranda(request: Request):
    """Pintu masuk webapp. Belum masuk → halaman masuk."""
    akun = await akun_opsional(request)
    if akun is None:
        return RedirectResponse("/masuk", status_code=303)
    return render(request, "beranda.html")


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
