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
from fastapi.staticfiles import StaticFiles

from app.bots.registry import build_bots, run_polling
from app.config import settings
from app.database import SessionLocal
from app.services.dashboard import dashboard_data, render_dashboard_html
from app.penggilingan.gudang1.services.sinkron_bobot import run_sinkron_bobot_poller
from app.services.scheduler import run_late_drying_scheduler
from app.services.seed import seed_master
from app.web.auth import router as auth_router
from app.web.internal import router as internal_router
from app.bots.common import can_see_financials
from app.web.nav import jumlah_menunggu
from app.web.aksi_inventory import router as aksi_inventory_router
from app.web.aksi_undo import router as aksi_undo_router
from app.web.laporan import router as laporan_router
from app.web.layar_berjalan import router as berjalan_router
from app.web.pengaturan import router as pengaturan_router
from app.web.mode_uji import router as mode_uji_router
from app.web.lihat_sebagai import router as lihat_sebagai_router
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
from app.web.tampilan import BASE_DIR, render

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
app.include_router(aksi_inventory_router)
app.include_router(aksi_undo_router)
app.include_router(laporan_router)
app.include_router(berjalan_router)
app.include_router(pengaturan_router)
app.include_router(mode_uji_router)
app.include_router(lihat_sebagai_router)
app.include_router(internal_router)
app.include_router(auth_router)
app.include_router(pengguna_router)
class StatisTerCache(StaticFiles):
    """Berkas statis yang tidak ditanyakan ulang setiap pindah halaman.

    Tanpa `Cache-Control`, peramban hanya punya ETag — dan ETag berarti ia
    TETAP bertanya "apakah berubah?" pada tiap navigasi. Jawabannya "tidak",
    tetapi pertanyaannya sendiri memakan satu perjalanan pulang-pergi ke
    server, dan server ini di San Francisco: ~270 ms sekali tanya, dua berkas,
    tiap halaman.

    Aman disimpan setahun karena setiap alamatnya bercap versi
    (`app.css?v=13`): berkas yang berubah dimintakan dengan alamat baru, jadi
    salinan lama tak pernah terpakai. Yang TIDAK bercap versi — ikon, manifest
    — diberi umur pendek supaya tetap bisa diperbarui.
    """

    async def get_response(self, path: str, scope):
        balasan = await super().get_response(path, scope)
        bercap = b"v=" in dict(scope).get("query_string", b"")
        balasan.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if bercap else "public, max-age=3600"
        )
        return balasan


app.mount("/static", StatisTerCache(directory=str(BASE_DIR / "static")), name="static")


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
    """Pintu masuk webapp: keadaan pabrik hari ini + pintu ke halaman lain.

    Angkanya diambil dari `dashboard_data` — bagian `operasional` saja, yang
    murni jumlah dan tak memuat data uang, sehingga aman dilihat operator.
    """
    akun = await akun_opsional(request)
    if akun is None:
        return RedirectResponse("/masuk", status_code=303)

    from sqlalchemy import func, select

    from app.models import ProduksiAkun

    o, jml_akun = {}, 0
    try:
        async with SessionLocal() as db:
            o = (await dashboard_data(db)).get("operasional", {}) or {}
            jml_akun = (await db.execute(select(func.count(ProduksiAkun.id)))).scalar_one()
    except Exception:
        log.exception("Keadaan pabrik gagal dimuat (beranda tetap tampil)")

    # Hanya kunci yang dikenal yang jadi pesan — teks bebas dari URL tak
    # pernah ditampilkan, supaya halaman ini tak bisa dipakai menitipkan
    # kalimat palsu lewat tautan.
    _PESAN = {"sandi-diganti": "Kata sandi berhasil diganti."}

    gabah = o.get("gabah_hari_ini", {}) or {}
    silo = o.get("silo", []) or []
    return render(
        request, "beranda.html",
        gabah_kg=gabah.get("total_kg", 0) or 0,
        gabah_batch=gabah.get("batch", 0) or 0,
        pengeringan=len(o.get("pengeringan", []) or []),
        # Daftarnya, bukan cuma cacahnya: "1 lot" tak memberi tahu apa pun
        # tentang sudah sejauh mana ia kering.
        lot_kering=o.get("pengeringan", []) or [],
        silo_terisi=sum(1 for s in silo if s.get("terisi")),
        silo_total=len(silo),
        giling=len(o.get("giling", []) or []),
        stok_pk=(o.get("stok_pk", {}) or {}).get("total", 0) or 0,
        stok_pk_maks=(o.get("stok_pk", {}) or {}).get("maks", 0) or 0,
        jml_akun=jml_akun,
        MENUNGGU=await jumlah_menunggu(akun.user),
        # Menentukan kalimat di kartu Laporan, bukan hak aksesnya — yang itu
        # diputuskan ulang di `laporan.py` untuk tiap laporan yang diminta.
        boleh_uang=bool(akun.user and can_see_financials(akun.user)),
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": settings.claude_model,
        "bots": list(settings.bot_tokens.keys()),
    }


@app.get("/aksi", response_class=HTMLResponse)
async def halaman_aksi(request: Request):
    """Layar pencatatan. Daftar aksi & bentuk formulirnya datang dari server
    (`/miniapp/actions/menu`), jadi menambah aksi tak perlu layar baru."""
    from app.web.security import butuh_akun

    akun = await butuh_akun(request)
    # `buka` datang dari layar Berjalan ATAU dari benda di layar ini sendiri:
    # menekan satu baris harus membuka formulir yang menutupnya, bukan
    # menurunkan orang di daftar aksi lalu menyuruhnya mencari sendiri.
    #
    # Bendanya diambil dari sumber yang SAMA dengan layar Berjalan. Dua daftar
    # yang disusun terpisah akan berselisih cepat atau lambat, dan yang salah
    # adalah yang lebih jarang dibuka orang.
    from app.services import berjalan as svc

    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)
    return render(request, "aksi.html", kembali="/",
                  buka=request.query_params.get("buka") or "",
                  nilai=request.query_params.get("nilai") or "",
                  # Hanya yang BELUM PUNYA TEMPAT. Yang sudah berada di
                  # mesin atau silo pindah ke layar Sedang berjalan berikut
                  # tindakannya — kartu yang sama muncul di dua tempat adalah
                  # dua tempat di kepala orang, dan cepat atau lambat keduanya
                  # berbeda isi.
                  menunggu=b.menunggu, berjalan=[], lama=svc._lama,
                  MENUNGGU=b.jumlah_menunggu)


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
