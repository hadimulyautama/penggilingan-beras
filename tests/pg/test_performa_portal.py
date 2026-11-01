"""Sesi lama tetap sah, diperpanjang tanpa menghidupkan sesi yang dicabut."""
import time

import pytest
from sqlalchemy import select

from app.models.portal import PortalAccount
from app.web.portal import security as portal_security
from hmu_identitas import token as tokens
from tests.pg.test_portal_pelanggan import portal, qc, client, token

pytestmark = pytest.mark.asyncio


async def test_sesi_12_jam_lama_diperpanjang_saat_membaca(pg, portal):
    account = portal.accounts[0]
    lama = tokens.buat_token(portal_security.key(), akun_id=account.id,
        versi=account.token_version, umur_detik=12 * 3600,
        ekstra={"pid": account.pelanggan_id})
    async with client() as c:
        c.cookies.set(portal_security.COOKIE, lama, domain="uji.local", path="/pelanggan")
        r = await c.get("/pelanggan/laporan")
        assert r.status_code == 200
        headers = r.headers.get_list("set-cookie")
        cookie = next(h for h in headers if h.startswith(portal_security.COOKIE + "="))
        assert "Max-Age=2592000" in cookie and "HttpOnly" in cookie and "Path=/pelanggan" in cookie
        baru = tokens.baca_token(portal_security.key(), c.cookies.get(portal_security.COOKIE))
        assert baru["exp"] - time.time() > 29 * 86400
        # Sesi tidak ditandatangani ulang pada setiap kunjungan.
        berikut = await c.get("/pelanggan/laporan")
        assert not any(h.startswith(portal_security.COOKIE + "=") for h in berikut.headers.get_list("set-cookie"))


async def test_sesi_dicabut_tidak_diperpanjang(pg, portal):
    async with client(portal.accounts[0]) as c:
        async with pg() as db:
            a = await db.get(PortalAccount, portal.accounts[0].id)
            a.token_version += 1
            await db.commit()
        r = await c.get("/pelanggan/laporan")
        assert r.status_code == 401
        assert not any(h.startswith(portal_security.COOKIE + "=") for h in r.headers.get_list("set-cookie"))


async def test_keluar_tidak_ditimpa_perpanjangan_sesi(pg, portal):
    async with client() as c:
        c.cookies.set(portal_security.COOKIE, portal_security.issue(portal.accounts[0]), domain="uji.local", path="/pelanggan")
        halaman = await c.get("/pelanggan/laporan")
        hasil = await c.post("/pelanggan/keluar", data={"_csrf": token(halaman)})
        assert hasil.status_code == 303
        cookie = next(h for h in hasil.headers.get_list("set-cookie") if h.startswith(portal_security.COOKIE + "="))
        assert "Max-Age=0" in cookie
        assert (await c.get("/pelanggan/laporan")).status_code == 401
