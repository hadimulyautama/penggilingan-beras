"""Alamat lama `/miniapp/*` masih dilayani sebagai `/api/*` (alias peralihan)."""
from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_alamat_lama_dilayani_seperti_yang_baru():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji") as c:
        lama = await c.get("/miniapp/me")
        baru = await c.get("/api/me")
    # Tanpa sesi keduanya ditolak 401 — bukan 404: alamatnya dikenal.
    assert lama.status_code == baru.status_code == 401


def test_tak_ada_lagi_awalan_miniapp_di_rute():
    assert not any(getattr(r, "path", "").startswith("/miniapp") for r in app.routes)
