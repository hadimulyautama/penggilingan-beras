"""Alur utama satu konfirmasi, API asli, database uji dan browser terisolasi."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select, func
from app.models import User, OutgoingRecord, ActivityLog
from tests.pg.test_barang_keluar import gudang, _klien, _stok
from tests.pg.test_kiriman_pelanggan import _buat, _data
from hmu_identitas import peran as P

BASE = 'http://127.0.0.1:59996'
OUT = Path(__file__).resolve().parents[2] / 'output/muat-sekali-20261107'
pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def browser_client(client, width, fault=None):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
        await ctx.add_cookies([{'name': k.name, 'value': k.value, 'url': BASE} for k in client.cookies.jar])
        writes = []
        async def request(route):
            req = route.request
            if not req.url.startswith(BASE + '/'):
                await route.abort(); return
            target = urlsplit(req.url)
            if target.path == '/api/aliran':
                await route.fulfill(status=204, body=''); return
            if req.method != 'GET': writes.append(target.path)
            response = await client.request(req.method, target.path + ('?' + target.query if target.query else ''),
                content=req.post_data_buffer,
                headers={k: v for k, v in req.headers.items() if k.lower() in ('content-type', 'x-csrf-token', 'x-pindah', 'accept')})
            if fault and fault(target.path, req.method):
                await route.abort(); return
            headers = {k: v for k, v in response.headers.items()
                       if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')}
            await route.fulfill(status=response.status_code, headers=headers, body=response.content)
        await ctx.route('**/*', request)
        page = await ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        try: yield page, writes, errors
        finally:
            await ctx.close(); await browser.close()


async def state(pg, rs):
    async with pg() as db:
        return [(await db.get(OutgoingRecord, r.rec.id)).status for r in rs]


@pytest.mark.parametrize('width,role', [(1440, P.OPERATOR), (390, P.OPERATOR), (320, P.SUPERADMIN)])
async def test_satu_konfirmasi_hanya_perintah_terpilih_stok_audit(pg, gudang, width, role):
    from playwright.async_api import expect
    rs = await _buat(pg, gudang, await _data(pg, gudang))
    async with pg() as db:
        user = await db.get(User, gudang['op']); user.role = role; await db.commit()
    async with await _klien(pg, gudang['op'], 'uji-muat-sekali', mode='operator') as c:
        async with browser_client(c, width) as (page, writes, errors):
            await page.goto(BASE + f'/muatan?perintah={rs[0].rec.id}')
            await expect(page.locator('[data-muat-semua]').first).to_be_enabled()
            assert await page.locator('input[data-item]').count() == 0
            assert await _stok(pg, gudang) == 10000
            OUT.mkdir(parents=True, exist_ok=True)
            await page.locator(f'[data-muat-semua="{rs[0].rec.id}"]').evaluate('e=>{e.click();e.click()}')
            await expect(page.locator(f'#muat-pelanggan-{rs[0].rec.id} .mr-status')).to_have_text('Selesai muat')
            assert await page.get_by_role('button', name='Konfirmasi muat & selesai', exact=True).count() == 0
            assert writes.count('/api/actions/muat-semua') == 1
            assert await state(pg, rs) == ['dimuat', 'perintah']
            assert await _stok(pg, gudang) == 9450
            assert not await page.locator(f'#muat-pelanggan-{rs[0].rec.id} [data-muat-semua]').count()
            assert await page.locator(f'[data-muat-semua="{rs[1].rec.id}"]').is_enabled()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(OUT/f'selesai-{width}.png'), full_page=True)
            assert not errors, errors
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(
            ActivityLog.aksi == 'barang_keluar_muat')) == 1
        assert (await db.get(OutgoingRecord, rs[0].rec.id)).waktu_verifikasi is None


async def test_respons_hilang_setelah_commit_tidak_kirim_ulang(pg, gudang):
    from playwright.async_api import expect
    rs = await _buat(pg, gudang, await _data(pg, gudang))
    async with await _klien(pg, gudang['op'], 'uji-muat-putus', mode='operator') as c:
        async with browser_client(c, 390, lambda path, method: path == '/api/actions/muat-semua') as (page,writes,errors):
            await page.goto(BASE + f'/muatan?perintah={rs[0].rec.id}')
            await page.locator(f'[data-muat-semua="{rs[0].rec.id}"]').click()
            await expect(page.locator('[data-galat]')).to_contain_text('belum dapat dipastikan')
            assert await _stok(pg, gudang) == 9450
            await page.get_by_role('button', name='Periksa muatan terbaru', exact=True).click()
            await expect(page.locator(f'#muat-pelanggan-{rs[0].rec.id} .mr-status')).to_have_text('Selesai muat')
            assert await page.get_by_role('button', name='Konfirmasi muat & selesai', exact=True).count() == 0
            assert writes.count('/api/actions/muat-semua') == 1
            assert await state(pg, rs) == ['dimuat','perintah']
            assert not errors, errors


async def test_admin_baca_dan_jalur_aktual_tetap_tersedia(pg, gudang):
    from playwright.async_api import expect
    rs = await _buat(pg, gudang, await _data(pg, gudang))
    async with await _klien(pg, gudang['adm'], 'uji-muat-admin') as c:
        async with browser_client(c, 390) as (page,writes,errors):
            await page.goto(BASE + f'/muatan?perintah={rs[0].rec.id}')
            await expect(page.locator('[data-muat-semua]').first).to_be_disabled()
            assert not writes
    async with await _klien(pg, gudang['op'], 'uji-muat-beda', mode='operator') as c:
        async with browser_client(c, 390) as (page,writes,errors):
            await page.goto(BASE + f'/muatan?perintah={rs[0].rec.id}')
            await page.get_by_role('button', name='Muatan berbeda dari perintah', exact=True).first.click()
            await expect(page.locator('input[data-item]').first).to_be_visible()
            await page.locator('input[data-item]').first.fill('10')
            await page.locator(f'[data-muat-semua="{rs[0].rec.id}"]').click()
            await expect(page.locator('[data-galat]')).to_contain_text('belum disimpan')
            assert await page.locator('input[data-item]').first.input_value() == '10'
            assert '/api/actions/muat-semua' not in writes
            assert not errors, errors
    assert await _stok(pg, gudang) == 10000


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('gudang_kode,lihat', [('g1', False), ('g2', False), ('g1', True), ('g2', True)])
async def test_login_operator_dan_lihat_sebagai_pintu_muat(pg, gudang, width, gudang_kode, lihat):
    from playwright.async_api import expect
    from app.models import Warehouse
    from app.web import security
    rs = await _buat(pg, gudang, await _data(pg, gudang))
    uid = gudang['adm'] if lihat else gudang['op']
    async with pg() as db:
        user = await db.get(User, uid)
        user.role = P.SUPERADMIN if lihat else P.OPERATOR
        user.default_warehouse_id = await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi == gudang_kode))
        assert user.default_warehouse_id
        await db.commit()
    async with await _klien(pg, uid, 'uji-pintu-muat', mode='admin' if lihat else 'operator') as c:
        # Jalankan autentikasi sebenarnya, bukan hanya token fixture.
        c.cookies.clear()
        from tests.pg.test_lembar_muatan import cap_formulir
        await c.get('/masuk')
        login = await c.post('/masuk', headers={'X-CSRF-Token':cap_formulir(c)}, data={'username':'uji-pintu-muat','sandi':'rahasia123','tujuan':'/muatan'})
        assert login.status_code == 303, login.text
        assert c.cookies.get(security.NAMA_COOKIE)
        if lihat:
            c.cookies.set('produksi_lihat', 'operator:' + gudang_kode)
        async with browser_client(c, width) as (page, writes, errors):
            await page.goto(BASE + f'/muatan?perintah={rs[0].rec.id}')
            OUT.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(OUT/f'pintu-{gudang_kode}-{lihat}-{width}.png'), full_page=True)
            expected = '/muatan' if gudang_kode == 'g1' else '/barang-keluar'
            links = page.locator('a').filter(has_text='Pengiriman')
            assert await links.count() >= 1
            for href in await links.evaluate_all('(xs)=>xs.map(x=>x.getAttribute("href"))'):
                assert href == expected
            await page.locator(f'[data-muat-semua="{rs[0].rec.id}"]').click()
            await expect(page.locator(f'#muat-pelanggan-{rs[0].rec.id} .mr-status')).to_have_text('Selesai muat')
            assert writes.count('/api/actions/muat-semua') == 1
            assert await page.get_by_role('button', name='Konfirmasi muat & selesai', exact=True).count() == 0
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors, errors
        # Pintu G1 tidak memperluas izin daftar penuh.
        response = await c.get('/barang-keluar')
        assert response.status_code == (403 if gudang_kode == 'g1' else 200)
    assert await state(pg, rs) == ['dimuat', 'perintah']
    assert await _stok(pg, gudang) == 9450
