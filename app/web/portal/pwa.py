"""Identitas pemasangan pelanggan, terpisah dari PWA kerja pabrik."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/pelanggan", include_in_schema=False)
STATIC = Path(__file__).resolve().parents[1] / "static"


@router.get("/manifest.webmanifest")
async def manifest():
    # ID stabil membedakan dua aplikasi pada origin yang sama. Cakupan ini
    # untuk jendela aplikasi; izin data tetap diperiksa server pada tiap baca.
    return JSONResponse({
        "id": "/pelanggan/",
        "name": "PadiFlow Pelanggan",
        "short_name": "PadiFlow Pelanggan",
        "description": "Stok, pekerjaan, riwayat, dan laporan barang jasa milik Anda.",
        "lang": "id",
        "start_url": "/pelanggan/",
        "scope": "/pelanggan/",
        "display": "standalone",
        "background_color": "#f5f5ef",
        "theme_color": "#f5f5ef",
        "icons": [
            {"src": f"/static/pelanggan-ikon-{size}.png?v=1",
             "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}
            for size, purpose in ((192, "any"), (512, "any"), (512, "maskable"))
        ],
    }, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@router.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC / "pelanggan-sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache",
                                 "Service-Worker-Allowed": "/pelanggan/"})
