"""Klik muat memakai HTML/API asli dan browser pada data Postgres sementara."""
from urllib.parse import urlsplit
import pytest
from sqlalchemy import select
from app.models import User, ActivityLog
from tests.pg.test_barang_keluar import gudang, _perintah, _klien, _stok
from hmu_identitas import peran as P

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]

from contextlib import asynccontextmanager
import asyncio
import socket


@asynccontextmanager
async def server_uji():
    """HTTP nyata agar redirect 303 melewati perilaku browser sebenarnya.

    Route.fulfill hanya mencegat permintaan pertama dalam rantai redirect;
    URL palsu tanpa server membuat tujuan 303 menjadi ERR_CONNECTION_REFUSED.
    Lifespan mati: fixture pg sudah menyiapkan data dan master pengujian.
    """
    import uvicorn
    from app.main import app
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    base = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_level='error'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError('Server uji berhenti sebelum siap')
                await asyncio.sleep(.01)
        yield base
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()



@pytest.mark.parametrize('role',[P.OPERATOR,P.SUPERADMIN])
async def test_operator_dan_super_admin_membuka_muat_dari_perintah(pg,gudang,role):
    from playwright.async_api import async_playwright, expect
    r=await _perintah(pg,gudang,karung=40)
    uid=gudang['op'] if role==P.OPERATOR else gudang['adm']
    async with pg() as db:
        u=await db.get(User,uid);u.role=role;await db.commit()
        audit_awal=(await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()
    async with await _klien(pg,uid,'uji-browser-muat') as client, server_uji() as base:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            ctx=await browser.new_context(viewport={'width':390,'height':840},service_workers='block')
            await ctx.add_cookies([{'name':k.name,'value':k.value,'url':base} for k in client.cookies.jar])
            writes=[]
            async def aplikasi(route):
                req=route.request
                if not req.url.startswith(base+'/'):
                    await route.abort();return
                if req.method!='GET':
                    writes.append(req.url);await route.abort();return
                target=urlsplit(req.url)
                if target.path=='/api/aliran':
                    await route.fulfill(status=204,body='');return
                await route.continue_()
            await ctx.route('**/*',aplikasi)
            page=await ctx.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto(base+f'/barang-keluar/{r.rec.id}')
            await page.get_by_role('link',name='Catat muatan',exact=True).click()
            await expect(page).to_have_url(base+f'/muatan?perintah={r.rec.id}')
            await expect(page.locator('[data-catat-muatan]')).to_be_visible()
            await expect(page.get_by_role('button',name='Isi sesuai perintah',exact=True)).to_be_enabled()
            assert not errors,errors
            assert not writes,writes
            await ctx.close();await browser.close()
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        assert (await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()==audit_awal
        assert (await db.get(User,uid)).role==role
