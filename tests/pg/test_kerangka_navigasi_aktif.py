"""PINDAH native membedakan navigasi kerangka dan pembacaan ulang data.

Browser tidak memakai listener HTTP. Request aslinya, termasuk Sec-Fetch,
diteruskan ke ASGI dan PostgreSQL fixture. Dua barrier menahan jawaban HTML
dan JSON secara terpisah; tidak ada sleep yang dianggap sebagai bukti siap.
UJI_BROWSER memilih mesin profil resmi (default Chromium, juga WebKit).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Error as BrowserError, async_playwright, expect
from sqlalchemy import text

from hmu_identitas import peran as P
from tests.pg.test_halaman_bertahap import proses_aktif  # noqa: F401
from tests.pg.test_pk_karung import batch_baru, dunia  # noqa: F401
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio
BASE = 'http://127.0.0.1:59996'
KODE_BEBAS = 'PKB-NAV-KERANGKA-01'
GUDANG = 'Gudang 2 - Kerangka uji'


async def _sidik(pg):
    async with pg() as db:
        names = (await db.scalars(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "ORDER BY tablename"))).all()
        result = {}
        for name in names:
            ident = name.replace('"', '""')
            rows = (await db.scalars(text(
                'SELECT row_to_json(x)::text FROM "' + ident +
                '" x ORDER BY row_to_json(x)::text'))).all()
            result[name] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        return result


@pytest.fixture
async def stok_navigasi(pg, proses_aktif, dunia):
    # Proses aktif memakai partai sendiri. Partai ini tetap bebas dan berasal
    # dari writer fixture publik yang sama, bukan stok buatan lewat SQL.
    async with pg() as db:
        _, _, intake = await batch_baru(db, dunia, n=20, w=1000,
                                        kode=KODE_BEBAS)
        return dict(proses=proses_aktif, intake_id=intake.id)


class _JawabanDitahan:
    def __init__(self):
        self.mulai = asyncio.Event()
        self.lepas = asyncio.Event()
        self.selesai = asyncio.Event()
        self.jumlah = 0

    async def tunggu(self):
        self.jumlah += 1
        self.mulai.set()
        await asyncio.wait_for(self.lepas.wait(), 20)


class _ASGIBrowser:
    def __init__(self, client):
        self.client = client
        self.html = _JawabanDitahan()
        self.data = _JawabanDitahan()
        self.requests = []
        self.writes = []
        self.allow_data_abort = False
        self.aborted_data = []

    async def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if not request.url.startswith(BASE + '/'):
            await route.abort()
            return
        if request.method != 'GET':
            self.writes.append((request.method, url.path))
            await route.abort()
            return
        headers = await request.all_headers()
        # Jangan mengarang Sec-Fetch untuk memaksa renderer. Browserlah yang
        # memilih navigate/document atau fetch; ASGI mendapat pilihan itu.
        forwarded = {k: v for k, v in headers.items() if k.lower() in {
            'accept', 'user-agent', 'sec-fetch-mode', 'sec-fetch-dest',
            'sec-fetch-site', 'sec-fetch-user', 'x-pindah',
            'x-kerangka-halaman', 'x-portal-navigasi', 'x-meja-lihat'}}
        self.requests.append(dict(path=url.path, query=url.query,
                                  headers=forwarded))
        if url.path == '/api/aliran':
            await route.fulfill(status=204, body='')
            return
        if url.path == '/api/keadaan':
            from app.web.tampilan import VERSI
            await route.fulfill(json={'n': 'fixture-kerangka', 'versi': str(VERSI)})
            return
        path = url.path + ('?' + url.query if url.query else '')
        response = await self.client.get(path, headers=forwarded)
        barrier = None
        if (url.path == '/stok' and not url.query and
                forwarded.get('x-pindah') == '1' and
                forwarded.get('x-kerangka-halaman') == '1'):
            barrier = self.html
            assert response.status_code == 200
            assert 'data-halaman-bertahap' in response.text
        elif url.path == '/api/halaman-bertahap/stok' and not url.query:
            barrier = self.data
            assert response.status_code == 200
            assert KODE_BEBAS in response.json()['html']
        try:
            if barrier:
                await barrier.tunggu()
            await route.fulfill(status=response.status_code, headers={
                k: v for k, v in response.headers.items() if k.lower() not in {
                    'content-length', 'content-encoding', 'transfer-encoding'}},
                body=response.content)
        except BrowserError:
            # Keluar dari halaman memang boleh membatalkan GET lama. Kasus
            # normal tidak mengizinkan exception ini lewat tanpa gagal.
            if not (self.allow_data_abort and barrier is self.data):
                raise
            self.aborted_data.append(url.path)
        finally:
            if barrier:
                barrier.selesai.set()

    def bersihkan(self):
        self.html.lepas.set()
        self.data.lepas.set()


@asynccontextmanager
async def _browser(client, width):
    engine = os.getenv('UJI_BROWSER', 'chromium')
    assert engine in {'chromium', 'webkit'}, engine
    bridge = _ASGIBrowser(client)
    async with async_playwright() as pw:
        browser = await getattr(pw, engine).launch()
        context = await browser.new_context(
            viewport={'width': width, 'height': 840},
            service_workers='block', reduced_motion='reduce')
        try:
            await context.add_cookies([
                dict(name=x.name, value=x.value, url=BASE)
                for x in client.cookies.jar])
            await context.route('**/*', bridge.route)
            page = await context.new_page()
            yield page, bridge
        finally:
            bridge.bersihkan()
            await context.close()
            await browser.close()


async def _buka_stok_dari_menu(page, bridge, width):
    response = await page.goto(BASE + '/barang-masuk')
    assert response and response.status == 200
    await page.wait_for_function(
        "typeof window.PINDAH?.aturKerangkaHalaman === 'function'")
    if width < 900:
        await page.locator('#buka-laci').click()
    link = page.locator('#laci a[href="/stok"]').first
    await expect(link).to_be_visible()
    # Fokus keyboard memakai tautan produk yang sama, tanpa memanggil fungsi
    # pindah dari tes atau mengganti fetch milik produk.
    await link.focus()
    await link.press('Enter')
    await asyncio.wait_for(bridge.html.mulai.wait(), 10)
    await expect(page).to_have_url(BASE + '/stok')
    await expect(page.locator('.halaman-memuat')).to_be_visible(timeout=700)
    await expect(page.locator('#laci a[href="/stok"]').first).to_have_attribute(
        'aria-current', 'page')
    assert not bridge.html.lepas.is_set()
    assert not bridge.data.mulai.is_set()
    bridge.html.lepas.set()
    await asyncio.wait_for(bridge.data.mulai.wait(), 10)
    root = page.locator('[data-halaman-bertahap][data-kind="stok"]')
    await expect(root.get_by_role('heading', name='Stok', exact=True)).to_be_visible()
    await expect(root.locator('form[role="search"] input[name="cari"]')).to_be_visible()
    await expect(root.locator('summary', has_text='Filter')).to_be_visible()
    columns = root.locator('th[scope="col"]')
    assert await columns.count() >= 6
    await expect(columns.filter(has_text='Berat tersedia')).to_have_count(1)
    await expect(root.locator('[data-shell-table-wrap]')).to_have_attribute('aria-busy', 'true')
    await expect(root.locator('[data-shell-message]')).to_contain_text('Memuat data')
    await expect(root.get_by_role('button', name='Detail', exact=True)).to_be_disabled()
    assert not bridge.data.lepas.is_set()
    return root


@pytest.mark.parametrize('peran', [P.OPERATOR, P.ADMIN])
@pytest.mark.parametrize('width', [390, 1280])
async def test_navigasi_kerangka_lalu_data_refresh_native_dan_kosong(
        pg, stok_navigasi, peran, width):
    async with await _klien(pg, peran=peran, gudang=GUDANG) as client:
        before = await _sidik(pg)
        async with _browser(client, width) as (page, bridge):
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await _buka_stok_dari_menu(page, bridge, width)
            bridge.data.lepas.set()
            content = page.locator('[data-halaman-isi="stok"]')
            await expect(content).to_be_visible()
            row = content.locator('.stok-mobile-list__baris' if width < 900 else '.stok-baris__tautan', has_text=KODE_BEBAS)
            await expect(row).to_be_visible()
            await expect(row.locator('.stok-mobile-list__berat' if width < 900 else '.stok-tabel__angka')).to_have_text('1.000 kg')
            assert bridge.html.jumlah == bridge.data.jumlah == 1
            document = next(r for r in bridge.requests if
                            r['path'] == '/barang-masuk')
            assert document['headers'].get('sec-fetch-mode') == 'navigate'
            assert document['headers'].get('sec-fetch-dest') == 'document'

            start = len(bridge.requests)
            await page.evaluate("""() => new Promise(resolve => {
                PINDAH.segarkan(() => resolve(true));
            })""")
            refresh = [r for r in bridge.requests[start:] if r['path'] == '/stok']
            assert refresh, 'Segarkan harus membaca server, bukan cache shell'
            assert all(r['headers'].get('x-pindah') == '1' and
                       'x-kerangka-halaman' not in r['headers'] for r in refresh)
            await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
            row = page.locator('.stok-mobile-list__baris' if width < 900 else '.stok-baris__tautan', has_text=KODE_BEBAS)
            await expect(row).to_be_visible()
            await expect(row.locator('.stok-mobile-list__berat' if width < 900 else '.stok-tabel__angka')).to_have_text('1.000 kg')
            await expect(page.locator('#sk-filter .sk-form-filter')).to_have_count(1)

            # Tab kosong tetap memiliki tabel dan alasan, bukan hilang seluruh
            # strukturnya. Tidak memakai respons kosong buatan dari router tes.
            tab = page.locator('nav[aria-label="Jenis stok"] a[href*="tab=karung"]').first
            await tab.focus()
            await tab.press('Enter')
            await page.wait_for_url('**/stok?**tab=karung**')
            await expect(page.locator('[data-halaman-isi="stok"]')).to_be_visible()
            empty = page.locator('[data-daftar-kosong]')
            await expect(empty).to_contain_text('Belum ada stok pada cakupan ini.')
            assert await empty.locator('th[scope="col"]').count() >= 6
            await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
            assert not bridge.writes, bridge.writes
            assert not errors, errors
        assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280])
async def test_data_stok_terlambat_tidak_mengganti_kabar(
        pg, stok_navigasi, width):
    async with await _klien(pg, peran=P.OPERATOR, gudang=GUDANG) as client:
        before = await _sidik(pg)
        async with _browser(client, width) as (page, bridge):
            await _buka_stok_dari_menu(page, bridge, width)
            bridge.allow_data_abort = True
            settled = asyncio.Event()
            def selesai(request):
                if urlsplit(request.url).path == '/api/halaman-bertahap/stok':
                    settled.set()
            page.on('requestfinished', selesai)
            page.on('requestfailed', selesai)
            await page.evaluate("""() => {
                window.__stokSesudahKeluar = 0;
                new MutationObserver(() => {
                    if(location.pathname === '/kabar' &&
                       document.querySelector('[data-halaman-isi="stok"]'))
                        window.__stokSesudahKeluar++;
                }).observe(document.body, {childList:true, subtree:true});
            }""")
            kabar = page.locator('a[href="/kabar"]:visible').first
            await kabar.focus()
            await kabar.press('Enter')
            await expect(page).to_have_url(BASE + '/kabar')
            await expect(page.locator('#isi-halaman section.kb[aria-label="Kabar"]')).to_be_visible()
            assert not bridge.data.lepas.is_set()
            bridge.data.lepas.set()
            await asyncio.wait_for(bridge.data.selesai.wait(), 10)
            await asyncio.wait_for(settled.wait(), 10)
            # Event penyelesaian jaringan lalu dua frame memberi kesempatan
            # callback respons bekerja; bukan sleep untuk menebak urutan.
            await page.evaluate("""() => new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve)))""")
            await expect(page).to_have_url(BASE + '/kabar')
            await expect(page.locator('[data-halaman-bertahap],[data-halaman-isi="stok"]')).to_have_count(0)
            assert await page.evaluate('window.__stokSesudahKeluar') == 0
            assert bridge.data.jumlah == 1
            assert not bridge.writes, bridge.writes
        assert await _sidik(pg) == before
