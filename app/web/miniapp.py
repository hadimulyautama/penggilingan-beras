"""Router Mini App Telegram. Fondasi: identitas + role per user (initData).

Endpoint tampilan (dashboard, stok, tugas) menyusul — semua memakai dependency
`require_miniapp_user` sehingga tiap request tahu SIAPA & role-nya (server-side).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.bots.common import can_see_financials, can_transfer_pk
from app.models import User
from app.web.deps import require_miniapp_user

router = APIRouter(prefix="/miniapp", tags=["miniapp"])


# Halaman peluncur minimal: buktikan login initData → role di dalam Telegram.
# Tampilan dashboard lengkap menyusul; ini fondasi "siapa yang membuka".
_LAUNCH_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Penggilingan Beras</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
 body{font-family:system-ui,sans-serif;margin:0;padding:24px;
      background:var(--tg-theme-bg-color,#fff);color:var(--tg-theme-text-color,#111)}
 .card{max-width:420px;margin:0 auto}
 .role{display:inline-block;padding:4px 10px;border-radius:999px;
       background:#e6f1fb;color:#0c447c;font-size:13px;margin-top:6px}
 h1{font-size:20px;font-weight:500;margin:0 0 4px} .muted{color:#888;font-size:14px}
 .err{color:#b3261e}
</style></head>
<body><div class="card">
 <h1 id="hi">Memuat…</h1>
 <div id="role"></div>
 <p class="muted" id="detail"></p>
</div>
<script>
 const tg = window.Telegram && window.Telegram.WebApp;
 if (tg) tg.ready();
 const initData = (tg && tg.initData) || "";
 fetch("/miniapp/me", {headers: {Authorization: "tma " + initData}})
   .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.status)))
   .then(u => {
     document.getElementById("hi").textContent = "Halo, " + u.nama;
     document.getElementById("role").innerHTML =
       '<span class="role">' + u.role + '</span>';
     document.getElementById("detail").textContent =
       u.permissions.see_financials ? "Akses data keuangan: ya" : "Akses data keuangan: tidak";
   })
   .catch(err => {
     document.getElementById("hi").innerHTML =
       '<span class="err">Gagal masuk</span>';
     document.getElementById("detail").textContent = String(err);
   });
</script></body></html>"""


@router.get("", response_class=HTMLResponse)
async def launch() -> HTMLResponse:
    """Halaman Mini App (dibuka dari tombol menu bot). Login otomatis via initData."""
    return HTMLResponse(_LAUNCH_HTML)


@router.get("/me")
async def me(user: User = Depends(require_miniapp_user)) -> dict:
    """Profil + izin user yang membuka Mini App (menentukan tampilan front-end)."""
    return {
        "id": user.id,
        "nama": user.nama,
        "role": user.role,
        "default_warehouse_id": user.default_warehouse_id,
        "permissions": {
            # Front-end memakai ini untuk menyembunyikan/menampilkan panel.
            "see_financials": can_see_financials(user),
            "transfer_pk": can_transfer_pk(user),
        },
    }
