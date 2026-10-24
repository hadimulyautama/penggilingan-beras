"""Pemasangan pelanggan tidak mengambil identitas atau cakupan PWA produksi."""
from io import BytesIO

import httpx
import pytest
from bs4 import BeautifulSoup
from PIL import Image

from app.main import app


@pytest.mark.asyncio
async def test_manifest_login_dan_ikon_tersedia_sebelum_masuk():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji") as c:
        page = await c.get("/pelanggan/masuk")
        soup = BeautifulSoup(page.text, "html.parser")
        href = soup.select_one('link[rel=manifest]')["href"]
        r = await c.get(href)
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
        assert "no-cache" in r.headers["cache-control"]
        manifest = r.json()
        assert manifest["name"] == manifest["short_name"] == "PadiFlow Pelanggan"
        assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/pelanggan/"
        assert manifest["display"] == "standalone"
        assert "orientation" not in manifest  # Desktop dan rotasi ponsel tetap bebas.
        assert soup.select_one('meta[name=apple-mobile-web-app-title]')["content"] == manifest["name"]
        assert soup.select_one('[data-pasang-app]')
        assert soup.select_one('script[src*="portal-pwa.js"]')
        icons = {icon["src"]: icon["sizes"] for icon in manifest["icons"]}
        icons[soup.select_one('link[rel=apple-touch-icon]')["href"]] = "180x180"
        for url, dimensions in icons.items():
            r = await c.get(url)
            assert r.status_code == 200
            image = Image.open(BytesIO(r.content))
            assert f"{image.width}x{image.height}" == dimensions
            assert image.getpixel((0, 0))[:3] == (232, 121, 36)
        internal = (await c.get("/static/manifest.json")).json()
        assert internal["start_url"] == internal["scope"] == "/"
        assert internal["name"].startswith("PadiFlow Produksi")
        assert all("pelanggan-ikon" not in icon["src"] for icon in internal["icons"])


@pytest.mark.asyncio
async def test_worker_khusus_pelanggan_tidak_menyimpan_data_atau_menghapus_cache_lain():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji") as c:
        r = await c.get("/pelanggan/sw.js")
        assert r.status_code == 200 and "javascript" in r.headers["content-type"]
        assert r.headers["service-worker-allowed"] == "/pelanggan/"
        assert "no-cache" in r.headers["cache-control"]
        assert "caches." not in r.text
        assert "fetch(req)" in r.text and "Cache-Control': 'no-store'" in r.text
        assert "Tanpa jaringan" in r.text
        # Memasang aplikasi tetap tidak memberikan sesi pelanggan/internal.
        assert (await c.get("/pelanggan/", follow_redirects=False)).headers["location"] == "/pelanggan/masuk"
        assert (await c.get("/pengaturan", follow_redirects=False)).status_code == 303
