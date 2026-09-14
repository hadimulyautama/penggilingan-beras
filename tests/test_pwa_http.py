"""Tahap A rasa native di Pos Produksi: service worker dari akar, /luring terbuka.

Perilaku di peramban (cache, offline, pil) diuji Playwright di repo tampilan;
di sini yang dijaga adalah pemasangannya di aplikasi INI: rutenya ada, dari
akar (bukan /static/), tak pernah di-cache peramban, dan /luring bisa diambil
tanpa sesi — service worker mengambilnya saat dipasang, sebelum siapa pun masuk.
"""
from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_sw_dan_luring_tersedia_tanpa_sesi():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji") as c:
        sw = await c.get("/sw.js?v=1")
        assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
        assert sw.headers["service-worker-allowed"] == "/"
        assert "no-cache" in sw.headers["cache-control"]
        assert "self.addEventListener('fetch'" in sw.text

        luring = await c.get("/luring")
        assert luring.status_code == 200 and "Tanpa jaringan" in luring.text
        # Halaman: no-store seperti halaman lain — yang menyimpannya hanya worker.
        assert "no-store" in luring.headers["cache-control"]
