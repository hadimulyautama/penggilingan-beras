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


from tests.pg.test_gabung_jasa import dunia  # noqa: F401


@pytest.mark.parametrize('kanal',['sse','cadangan'])
async def test_semua_peran_dan_portal_menerima_hasil_otomatis_sambil_menjaga_draf(pg,dunia,kanal,monkeypatch):
    from contextlib import AsyncExitStack
    from playwright.async_api import async_playwright, expect
    from tests.pg.test_tahap_stok import siapkan
    from tests.pg.test_portal_transit import _akun
    from tests.pg.test_portal_pelanggan import client as portal_client
    from tests.pg.test_stok_pk_g1_polesan import _klien as staff_client
    from app.penggilingan.gudang1.services.milling import log_progress
    from app.web.portal import live
    asli=live.aliran;connections=[]
    async def putus_sekali(request,halaman,jeda=2):
        connections.append(halaman)
        generator=asli(request,halaman,jeda)
        try:
            if len(connections)==1:
                yield await anext(generator)
                return
            async for packet in generator:yield packet
        finally:await generator.aclose()
    monkeypatch.setattr(live,'aliran',putus_sekali)
    kode,_=await siapkan(pg,dunia)
    account=await _akun(pg,dunia)
    async with AsyncExitStack() as stack:
        clients=[]
        for role,wh in [('operator',dunia['g1']),('operator',dunia['g2']),('admin',None),('superadmin',None)]:
            c=await stack.enter_async_context(await staff_client(pg,role=role,gudang_id=wh))
            clients.append((c,'/stok?pemilik=jasa'))
        clients.append((await stack.enter_async_context(portal_client(account)),'/pelanggan/barang-saya'))
        base=await stack.enter_async_context(server_uji())
        pw=await stack.enter_async_context(async_playwright())
        browser=await pw.chromium.launch()
        contexts=[];pages=[];writes=[]
        try:
            for c,path in clients:
                ctx=await browser.new_context(viewport={'width':390,'height':840},service_workers='block')
                contexts.append(ctx)
                if kanal=='cadangan':await ctx.add_init_script('window.EventSource=undefined')
                await ctx.add_cookies([{'name':k.name,'value':k.value,'url':base} for k in c.cookies.jar])
                async def guard(route):
                    if not route.request.url.startswith(base+'/') or route.request.method!='GET':
                        if route.request.method!='GET':writes.append(route.request.url)
                        await route.abort();return
                    await route.continue_()
                await ctx.route('**/*',guard)
                page=await ctx.new_page();await page.goto(base+('/pelanggan' if kanal=='cadangan' and path.startswith('/pelanggan') else path))
                await expect(page.locator('[data-tahap=hasil]')).to_contain_text('1.500')
                pages.append(page)
            async with pg() as db:
                await log_progress(db,user=await db.get(User,dunia['user']),kode_proses=kode,berat_kumulatif=1700)
                audit=(await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()
            for page in pages:
                await expect(page.locator('[data-tahap=hasil]')).to_contain_text('1.700',timeout=15000)
                # Isian inline belum tersimpan, termasuk setelah kehilangan fokus.
                await page.evaluate("""() => {const f=document.createElement('form');f.id='draf-uji';f.method='post';f.innerHTML='<input name="catatan" value=""><input type="hidden" name="pilihan" value=""><button type="reset">Batal draf</button>';document.querySelector('main').prepend(f);window.SEGAR_AMAN.ingat();}""")
                if page is pages[0]:await page.locator('#draf-uji [name=pilihan]').evaluate("el=>el.value='pilihan belum disimpan'")
                elif page is pages[-1]:await page.locator('#draf-uji [name=catatan]').evaluate("el=>el.value='jangan hilang'")
                else:await page.locator('#draf-uji [name=catatan]').fill('jangan hilang')
                await page.locator('h2').first.click()
            async with pg() as db:
                await log_progress(db,user=await db.get(User,dunia['user']),kode_proses=kode,berat_kumulatif=1900)
                expected=(await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()
            await pages[-1].wait_for_timeout(3500)
            for page in pages:
                if page is pages[0]:await expect(page.locator('#draf-uji [name=pilihan]')).to_have_value('pilihan belum disimpan')
                else:await expect(page.locator('#draf-uji [name=catatan]')).to_have_value('jangan hilang')
                await expect(page.locator('[data-tahap=hasil]')).to_contain_text('1.700')
                await page.locator('#draf-uji button').click()
                await expect(page.locator('[data-tahap=hasil]')).to_contain_text('1.900',timeout=15000)
            assert not writes
            if kanal=='sse':assert len(connections)>=2
            async with pg() as db:
                setelah=(await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()
                # Hanya operasi log_progress kedua yang boleh menambah audit.
                assert setelah==expected and set(audit).issubset(set(setelah))
        finally:
            for ctx in contexts:await ctx.close()
            await browser.close()
