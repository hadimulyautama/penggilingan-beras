"""Router Mini App Telegram: identitas + dashboard role-aware (form/tampilan).

Tiap endpoint memakai dependency `require_miniapp_user` → tahu SIAPA & role-nya
(server-side). Data dihitung ulang dari Service yang sama dengan bot (satu sumber
kebenaran). Operator tak menerima data keuangan (HPP/tugas verifikasi).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.bots.common import can_see_financials, can_transfer_pk
from app.database import SessionLocal
from app.models import User
from app.web.deps import require_miniapp_user

router = APIRouter(prefix="/miniapp", tags=["miniapp"])


@router.get("/me")
async def me(user: User = Depends(require_miniapp_user)) -> dict:
    """Profil + izin user (menentukan tampilan front-end)."""
    return {
        "id": user.id,
        "nama": user.nama,
        "role": user.role,
        "default_warehouse_id": user.default_warehouse_id,
        "permissions": {
            "see_financials": can_see_financials(user),
            "transfer_pk": can_transfer_pk(user),
        },
    }


def _clean(s: str) -> str:
    """Buang penanda Markdown agar rapi sebagai teks kartu."""
    return (s or "").replace("*", "").replace("_", "")


async def _hpp_terkini(db) -> str:
    """HPP beras dari penyosohan TERAKHIR; placeholder bila belum ada/lengkap."""
    from sqlalchemy import select
    from app.models import PolishingProcess
    from app.inventory.finished_goods import laporan_hpp_beras
    from app.inventory.packaging import InventoryError
    kode = (
        await db.execute(
            select(PolishingProcess.kode_proses).order_by(PolishingProcess.id.desc()).limit(1)
        )
    ).scalars().first()
    if not kode:
        return "Belum ada penyosohan."
    try:
        return _clean(await laporan_hpp_beras(db, kode))
    except InventoryError:
        return "Belum tersedia (menunggu data lengkap)."


@router.get("/dashboard")
async def dashboard(user: User = Depends(require_miniapp_user)) -> dict:
    """Snapshot dashboard sesuai role. Keuangan (HPP/tugas) hanya staff/admin."""
    fin = can_see_financials(user)
    from app.services.report import status_gudang1, pending_verifikasi
    from app.services.transfer import laporan_pk_siap_transfer
    from app.gudang2.service import laporan_stok_gudang2
    from app.inventory.finished_goods import (
        laporan_stok_barang_jadi, hitung_stok_bekatul, laporan_hpp_beras,
    )
    from app.inventory.packaging import laporan_stok_kemasan

    sections: list[dict] = []
    async with SessionLocal() as db:
        sections.append({"icon": "🌾", "title": "Gudang 1 — Selepan", "body": _clean(
            await status_gudang1(db) + "\n\n" + await laporan_pk_siap_transfer(db))})
        sections.append({"icon": "🏭", "title": "Gudang 2 — Penyosohan", "body": _clean(
            await laporan_stok_gudang2(db, financial=fin))})
        bekatul = float(await hitung_stok_bekatul(db))
        sections.append({"icon": "📦", "title": "Barang jadi & bekatul", "body": _clean(
            await laporan_stok_barang_jadi(db)
            + f"\n\n🌾 Bekatul curah: {bekatul:,.0f} kg".replace(",", "."))})
        sections.append({"icon": "🧺", "title": "Kemasan", "body": _clean(
            await laporan_stok_kemasan(db))})
        if fin:
            sections.append({"icon": "✅", "title": "Tugas verifikasi & QC", "body": _clean(
                await pending_verifikasi(db))})
            sections.append({"icon": "💰", "title": "HPP beras terkini",
                             "body": await _hpp_terkini(db)})

    return {
        "user": {"nama": user.nama, "role": user.role, "see_financials": fin},
        "sections": sections,
    }


_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Penggilingan Beras</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
 :root{--bg:var(--tg-theme-bg-color,#f4f5f7);--card:var(--tg-theme-secondary-bg-color,#fff);
   --tx:var(--tg-theme-text-color,#16181c);--mut:var(--tg-theme-hint-color,#8a8f98);
   --ac:var(--tg-theme-button-color,#2c7be5);--acx:var(--tg-theme-button-text-color,#fff);--bd:rgba(128,128,128,.18)}
 *{box-sizing:border-box}
 body{margin:0;padding:14px;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);font-size:15px;line-height:1.5}
 .top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 2px 14px}
 .hi{font-size:18px;font-weight:600} .role{font-size:12px;color:var(--mut)}
 .pill{display:inline-block;padding:2px 9px;border-radius:999px;background:var(--ac);color:var(--acx);font-size:11px;font-weight:600;text-transform:capitalize}
 .btn{border:0;background:var(--card);color:var(--ac);border:1px solid var(--bd);border-radius:10px;padding:8px 12px;font-size:13px;font-weight:600}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:13px 15px;margin-bottom:11px}
 .ct{font-size:13px;font-weight:600;color:var(--mut);margin:0 0 7px;letter-spacing:.02em}
 .cb{white-space:pre-wrap;word-break:break-word;margin:0;font-size:14px}
 .muted{color:var(--mut);text-align:center;padding:30px 0}
 .err{color:#d93025;text-align:center;padding:24px 0}
</style></head>
<body>
 <div class="top">
   <div><div class="hi" id="hi">Memuat…</div><div class="role" id="ts"></div></div>
   <button class="btn" id="rf" onclick="load()">↻ Segarkan</button>
 </div>
 <div id="app"><div class="muted">Memuat data…</div></div>
<script>
 const tg = window.Telegram && window.Telegram.WebApp;
 if (tg){ tg.ready(); tg.expand(); }
 const initData = (tg && tg.initData) || "";
 const H = {Authorization: "tma " + initData};
 function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
 async function load(){
   const app=document.getElementById("app");
   try{
     const r = await fetch("/miniapp/dashboard", {headers:H});
     if(!r.ok){ const e=await r.json().catch(()=>({})); throw (e.detail||("HTTP "+r.status)); }
     const d = await r.json();
     document.getElementById("hi").textContent = "Halo, " + d.user.nama;
     document.getElementById("ts").innerHTML = '<span class="pill">'+esc(d.user.role)+'</span>';
     app.innerHTML = d.sections.map(s =>
       '<div class="card"><p class="ct">'+esc(s.icon+" "+s.title)+'</p><pre class="cb">'+esc(s.body)+'</pre></div>'
     ).join("");
     if(!d.sections.length) app.innerHTML='<div class="muted">Belum ada data.</div>';
   }catch(err){
     document.getElementById("hi").textContent="Gagal masuk";
     app.innerHTML='<div class="err">'+esc(String(err))+'</div>';
   }
 }
 load();
</script></body></html>"""


@router.get("", response_class=HTMLResponse)
async def launch() -> HTMLResponse:
    """Halaman Mini App (dari tombol menu bot). Login otomatis via initData."""
    return HTMLResponse(_HTML)
