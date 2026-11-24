"""One-touch mobile sidebar with real native reads held independently of HTML.

The ASGI bridge blocks SW and closes SSE with204; this is not a PWA/live SSE
or physical-device proof. Every business response is a fresh authorized GET.
"""
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
import pytest
from playwright.async_api import Error as BrowserError, async_playwright, expect
from tests.pg.test_portal_pelanggan import portal, qc, client
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_halaman_bertahap import _sidik
from hmu_identitas.peran import SUPERADMIN

pytestmark = pytest.mark.asyncio
BASE = 'http://127.0.0.1:59994'
NATIVE = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
PORTAL_NATIVE = {'X-Portal-Navigasi': '1', 'Accept': 'text/html'}


def read_slot(path, headers, *, pelanggan, daftar, detail):
    """Actual native protocols; document/shell HTML is a separate barrier."""
    if not pelanggan and path == '/api/jasa-daftar':
        return 'list-data'
    if path not in {daftar, detail}:
        return None
    data = (headers.get('x-portal-navigasi') == '1' if pelanggan else
            headers.get('x-pindah') == '1' and headers.get('x-kerangka-halaman') != '1')
    return ('list-' if path == daftar else 'detail-') + ('data' if data else 'html')


@dataclass
class ReadGate:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    completed: asyncio.Event = field(default_factory=asyncio.Event)


async def two_frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


def expected_detail_tabs(native_html, pelanggan):
    doc = BeautifulSoup(native_html, 'html.parser')
    selector = '.giling-tabs [role=tab]' if pelanggan else '.jasa-detail-tab a'
    labels = [n.get_text(' ', strip=True) for n in doc.select(selector)]
    assert labels, 'Actual authorized detail must provide its native tab labels'
    return labels


async def framework(page, *, pelanggan, detail, labels=None):
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    if pelanggan:
        selector = '[data-portal-detail-frame]' if detail else '[data-portal-native-frame][data-portal-page="/riwayat-proses"]'
        root = page.locator(selector)
        await expect(root).to_be_visible(timeout=700)
        await expect(root.locator('h1')).to_be_visible()
        if detail:
            tabs = root.locator('[role=tab]')
            assert [text.strip() for text in await tabs.all_text_contents()] == labels
            for tab in await tabs.all():
                await expect(tab).to_be_disabled()
            assert await root.locator('[role=tabpanel] h2').count() > 0
        else:
            await expect(root.locator('form[role=search] input[type=search][name=q]')).to_be_enabled()
            await expect(root.locator('form[role=search] select[name=jenis]')).to_be_enabled()
            await expect(root.locator('.pelanggan-catatan-panel')).to_be_visible()
        assert not await root.locator('form[method=post],[name=_csrf]').count()
    elif detail:
        root = page.locator('[data-jasa-detail-kerangka]')
        await expect(root).to_be_visible(timeout=700)
        assert [text.strip() for text in await root.locator('.jasa-detail-tab a').all_text_contents()] == labels
        await expect(root.locator('[data-jasa-kontrol]')).to_be_visible()
        await expect(root.locator('.jasa-detail-angka')).to_be_visible()
        assert not await root.locator('form[method=post],[name=_csrf]').count()
        assert await root.locator('button:disabled').count() > 0
    else:
        root = page.locator('[data-jasa-bertahap]')
        await expect(root).to_be_visible(timeout=700)
        await expect(root.locator('input[type=search][name=cari]')).to_be_enabled()
        await expect(root.locator('[data-jasa-kontrol]')).to_be_visible()
        await expect(root.locator('.jasa-daftar[role=list]')).to_be_visible()
        await expect(root.locator('.jasa-baca-tindakan button')).to_be_disabled()
    return root


async def test_read_gate_classification_does_not_confuse_html_with_native_data():
    options = dict(pelanggan=False, daftar='/jasa', detail='/jasa/pelanggan/1')
    assert read_slot('/api/jasa-daftar', {}, **options) == 'list-data'
    assert read_slot('/jasa', {}, **options) == 'list-html'
    assert read_slot('/jasa', {'x-pindah': '1', 'x-kerangka-halaman': '1'}, **options) == 'list-html'
    assert read_slot('/jasa', {'x-pindah': '1'}, **options) == 'list-data'
    assert read_slot('/jasa/pelanggan/1', {'x-pindah': '1', 'x-kerangka-halaman': '0'}, **options) == 'detail-data'
    options = dict(pelanggan=True, daftar='/pelanggan/riwayat-proses', detail='/pelanggan/riwayat-giling/1')
    assert read_slot(options['daftar'], {}, **options) == 'list-html'
    assert read_slot(options['daftar'], {'x-portal-navigasi': '1'}, **options) == 'list-data'
    assert read_slot(options['detail'], {'x-portal-navigasi': '1'}, **options) == 'detail-data'
    assert read_slot('/other', {'x-portal-navigasi': '1'}, **options) is None


@pytest.mark.parametrize('pelanggan', [False, True])
@pytest.mark.parametrize('engine', os.environ.get('UJI_PONSEL_ENGINES', 'chromium').split(','))
@pytest.mark.parametrize('width', [320, 390])
async def test_sidebar_detail_sekali_sentuh(pg, portal, pelanggan, engine, width):
    asal = '/pelanggan/' if pelanggan else '/barang-masuk'
    daftar = '/pelanggan/riwayat-proses' if pelanggan else '/jasa'
    detail = (f'/pelanggan/riwayat-giling/{portal.process[0]["giling"]}' if pelanggan
              else f'/jasa/pelanggan/{portal.owners[0].id}')
    menu = '.portal-sidebar' if pelanggan else '#laci'
    buka = '.portal-menu-bawah' if pelanggan else '#buka-laci'
    tutup = '.portal-tutup-menu' if pelanggan else '#laci .pd-close'
    c = client(portal.accounts[0]) if pelanggan else await _klien(pg, peran=SUPERADMIN)
    active, all_gates, pending = {}, [], set()
    def arm(slot):
        gate = ReadGate(); active[slot] = gate; all_gates.append(gate); return gate
    list_html, list_data = arm('list-html'), arm('list-data')
    detail_html, detail_data = arm('detail-html'), arm('detail-data')
    writes, errors, bridge_errors = [], [], []
    closing = False
    async with c:
        native_headers = PORTAL_NATIVE if pelanggan else NATIVE
        # These are oracles only, never cached bodies served to browser reads.
        native_list = await c.get(daftar, headers=native_headers)
        assert native_list.status_code == 200
        links = BeautifulSoup(native_list.text, 'html.parser').select('main a[href]')
        detailHref = next(a['href'] for a in links if urlsplit(a['href']).path == detail)
        native_detail = await c.get(detailHref, headers=native_headers)
        assert native_detail.status_code == 200
        labels = expected_detail_tabs(native_detail.text, pelanggan)
        before = await _sidik(pg)
        async with async_playwright() as pw:
            browser = await getattr(pw, engine).launch()
            ctx = await browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=True,
                has_touch=True, device_scale_factor=2, service_workers='block', reduced_motion='reduce')
            await ctx.add_cookies([{'name': x.name, 'value': x.value, 'url': BASE} for x in c.cookies.jar])
            async def app(route):
                req = route.request; u = urlsplit(req.url)
                if closing or not req.url.startswith(BASE + '/'):
                    return await route.abort()
                if req.method != 'GET':
                    writes.append(u.path); return await route.abort()
                if u.path == '/api/aliran':
                    return await route.fulfill(status=204, body='')
                headers = {k.lower(): v for k, v in (await req.all_headers()).items()}
                slot = read_slot(u.path, headers, pelanggan=pelanggan, daftar=daftar, detail=detail)
                held = active.get(slot)
                # Forward the request's actual negotiated read shape. A shell
                # must never stand in for a fresh data response on refresh.
                native = {k: v for k, v in headers.items() if k in {
                    'x-pindah', 'x-kerangka-halaman', 'x-portal-navigasi', 'accept',
                    'sec-fetch-mode', 'sec-fetch-dest', 'sec-fetch-site', 'sec-fetch-user'}}
                job = asyncio.create_task(c.get(u.path + ('?' + u.query if u.query else ''), headers=native))
                pending.add(job)
                try:
                    response = await asyncio.wait_for(asyncio.shield(job), 60)
                    if held:
                        held.entered.set(); await asyncio.wait_for(held.release.wait(), 20)
                    await route.fulfill(status=response.status_code, body=response.content,
                        headers={k: v for k, v in response.headers.items() if k.lower() not in {
                            'content-length', 'content-encoding', 'transfer-encoding', 'set-cookie'}})
                except BrowserError as error:
                    if not closing and not req.failure:
                        bridge_errors.append(type(error).__name__)
                        raise
                finally:
                    pending.discard(job)
                    if held: held.completed.set()
            await ctx.route('**/*', app)
            page = await ctx.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
            await page.add_init_script("document.addEventListener('click',e=>{let a=e.target.closest('a[href]');if(a){window.taps=window.taps||{};window.taps[a.pathname]=(window.taps[a.pathname]||0)+1;window.lastTap=performance.now();}},true);")
            async def refresh_native():
                await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))" if pelanggan
                                    else 'PINDAH.muatPerubahan()')
            try:
                await page.goto(BASE + asal)
                await page.locator(buka).tap()
                await page.locator(menu + f' a[href="{daftar}"]').first.tap()
                await asyncio.wait_for(list_data.entered.wait(), 15)
                await framework(page, pelanggan=pelanggan, detail=False)
                await expect(page).to_have_url(BASE + daftar)
                assert not list_html.release.is_set(), 'Destination HTML must still be held'
                await page.locator(buka).tap()
                await expect(page.locator(menu)).to_be_visible()
                list_data.release.set(); list_html.release.set()
                await asyncio.wait_for(list_data.completed.wait(), 20); await two_frames(page)
                await expect(page.locator(menu)).to_be_in_viewport(ratio=.5, timeout=700)
                await page.locator(tutup).tap()
                await expect(page.locator('main a[href="' + detailHref + '"]').first).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                # Fresh native read is in flight before typing; response must
                # not replace the current input object, value or scroll state.
                refreshing = arm('list-data'); await refresh_native()
                await asyncio.wait_for(refreshing.entered.wait(), 15)
                search = page.locator('main input[type=search]').first
                await search.fill('ketikan belum dikirim')
                await search.evaluate('(el)=>window.inputAsli=el')
                top = await page.locator('main').evaluate('(el)=>{el.scrollTop=40;return el.scrollTop}')
                refreshing.release.set(); await asyncio.wait_for(refreshing.completed.wait(), 20)
                await two_frames(page)
                await expect(search).to_have_value('ketikan belum dikirim')
                assert await page.evaluate('window.inputAsli.isConnected')
                assert await page.locator('main').evaluate('(el)=>el.scrollTop') == top
                await search.fill(''); await search.evaluate('(el)=>el.blur()')
                # Negative stale-response control: a second old-list read is
                # released only after the one-tap detail framework is visible.
                stale = arm('list-data'); await refresh_native()
                await asyncio.wait_for(stale.entered.wait(), 15)
                await page.locator('main a[href="' + detailHref + '"]').first.tap()
                await asyncio.wait_for(detail_data.entered.wait(), 15)
                await framework(page, pelanggan=pelanggan, detail=True, labels=labels)
                await expect(page).to_have_url(BASE + detailHref)
                assert not detail_html.release.is_set(), 'Detail HTML must still be held'
                stale.release.set(); await asyncio.wait_for(stale.completed.wait(), 20); await two_frames(page)
                await framework(page, pelanggan=pelanggan, detail=True, labels=labels)
                await expect(page).to_have_url(BASE + detailHref)
                detail_data.release.set(); detail_html.release.set()
                await asyncio.wait_for(detail_data.completed.wait(), 20); await two_frames(page)
                await expect(page.locator('[data-portal-detail-frame]' if pelanggan else '[data-jasa-detail-kerangka]')).to_have_count(0, timeout=10000)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                taps = await page.evaluate('window.taps')
                assert taps[daftar] == taps[detail] == 1, taps
                assert not errors and not writes and not bridge_errors, (errors, writes, bridge_errors)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if pelanggan:
                    assert 'Rahasia Pelanggan B' not in await page.locator('main').inner_text()
                out = Path(os.environ.get('UJI_PONSEL_OUT', 'output/ponsel')); out.mkdir(parents=True, exist_ok=True)
                name = ('portal' if pelanggan else 'padiflow') + f'-{engine}-{width}'
                await page.screenshot(path=str(out / (name + '.png')))
                (out / (name + '.json')).write_text(json.dumps(dict(engine=engine, width=width, touch=True,
                    sidebar_taps=taps[daftar], detail_taps=taps[detail], independently_held_HTML_and_native_data=True,
                    old_list_response_ignored=True, menu_preserved=True, input_preserved=True,
                    scroll_preserved=True, measured_scroll_top=top, errors=errors, writes=writes)) + '\n')
                await page.go_back(); await expect(page).to_have_url(BASE + daftar)
                await expect(page.locator('.halaman-memuat')).to_have_count(0, timeout=10000)
            finally:
                closing = True
                for gate in all_gates: gate.release.set()
                if pending:
                    await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 65)
                await ctx.close(); await browser.close()
        assert await _sidik(pg) == before
