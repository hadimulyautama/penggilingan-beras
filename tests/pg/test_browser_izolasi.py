"""Permintaan browser harus menutup transaksi sebelum database uji dibersihkan."""
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.pg.test_pengeringan_desain_browser import browser

pytestmark = [pytest.mark.asyncio, pytest.mark.fondasi_multi]


@pytest.mark.parametrize('requests', [1, 3])
async def test_tutup_browser_menunggu_seluruh_pembacaan_db(pg, requests):
    app = FastAPI()
    started = 0
    ready = asyncio.Event()
    finished = []

    @app.get('/kosong', response_class=HTMLResponse)
    async def kosong():
        return '<!doctype html><title>Uji penutupan</title>'

    @app.get('/lambat/{ident}')
    async def lambat(ident: int):
        nonlocal started
        async with pg() as db:
            await db.execute(text('SELECT 1'))
            started += 1
            if started == requests:
                ready.set()
            # Pembacaan masih memegang transaksi saat browser mulai ditutup.
            await db.execute(text('SELECT pg_sleep(0.15)'))
        finished.append(ident)
        return {'id': ident}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='https://uji') as client:
        async with browser(client, 390) as page:
            await page.goto('https://uji/kosong')
            await page.evaluate('(n)=>{for(let i=0;i<n;i++)fetch("/lambat/"+i).catch(()=>{});}', requests)
            await asyncio.wait_for(ready.wait(), timeout=5)
        assert sorted(finished) == list(range(requests))
        assert pg.kw['bind'].pool.checkedout() == 0
