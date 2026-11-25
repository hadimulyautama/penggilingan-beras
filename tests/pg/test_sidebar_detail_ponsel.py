"""One-touch mobile sidebar with real native reads held independently of HTML.

The ASGI bridge blocks SW and closes SSE with204; this is not a PWA/live SSE
or physical-device proof. Every business response is a fresh authorized GET.
"""
import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import time
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
    if not pelanggan and path == '/api/halaman-bertahap/jasa':
        return 'list-data'
    if path not in {daftar, detail}:
        return None
    data = (headers.get('x-portal-navigasi') == '1' if pelanggan else
            headers.get('x-pindah') == '1' and headers.get('x-kerangka-halaman') != '1')
    return ('list-' if path == daftar else 'detail-') + ('data' if data else 'html')


@dataclass
class ReadGate:
    slot: str = ''
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    completed: asyncio.Event = field(default_factory=asyncio.Event)


async def two_frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


def diagnostic_path(value):
    """Only known route shape; no query, token, account ID or foreign URL."""
    path = urlsplit(value).path
    if path.startswith('/static/') and re.fullmatch(r'/static/[A-Za-z0-9_./-]{1,180}', path):
        return path
    if re.fullmatch(r'/(?:barang-masuk|jasa|api/(?:halaman-bertahap/jasa|keadaan|aliran)|pelanggan/?)', path):
        return path
    if re.fullmatch(r'/(?:jasa/pelanggan|pelanggan/riwayat-giling)/[0-9]+', path):
        return re.sub(r'/[0-9]+$', '/:id', path)
    if re.fullmatch(r'/pelanggan/(?:ringkasan|barang-masuk|barang-saya|jasa-saya|riwayat-proses|barang-keluar|laporan)', path):
        return path
    return '/other'


def diagnostic_headers(headers):
    return dict(pindah_1=headers.get('x-pindah') == '1',
        kerangka_1=headers.get('x-kerangka-halaman') == '1',
        kerangka_0=headers.get('x-kerangka-halaman') == '0',
        portal_1=headers.get('x-portal-navigasi') == '1',
        document=headers.get('sec-fetch-dest') == 'document',
        navigate=headers.get('sec-fetch-mode') == 'navigate',
        accept_json='application/json' in headers.get('accept', ''),
        accept_html='text/html' in headers.get('accept', ''))


def diagnostic_error(error):
    text = str(error)
    return dict(type=type(error).__name__, message_sha256=hashlib.sha256(text.encode()).hexdigest(),
        timeout='timeout' in text.lower(), access_control='access control' in text.lower(),
        network='network' in text.lower())


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
    assert read_slot('/api/halaman-bertahap/jasa', {}, **options) == 'list-data'
    assert read_slot('/api/jasa-daftar', {}, **options) is None  # Not a registered product endpoint.
    assert read_slot('/jasa', {}, **options) == 'list-html'
    assert read_slot('/jasa', {'x-pindah': '1', 'x-kerangka-halaman': '1'}, **options) == 'list-html'
    assert read_slot('/jasa', {'x-pindah': '1'}, **options) == 'list-data'
    assert read_slot('/jasa/pelanggan/1', {'x-pindah': '1', 'x-kerangka-halaman': '0'}, **options) == 'detail-data'
    options = dict(pelanggan=True, daftar='/pelanggan/riwayat-proses', detail='/pelanggan/riwayat-giling/1')
    assert read_slot(options['daftar'], {}, **options) == 'list-html'
    assert read_slot(options['daftar'], {'x-portal-navigasi': '1'}, **options) == 'list-data'
    assert read_slot(options['detail'], {'x-portal-navigasi': '1'}, **options) == 'detail-data'
    assert read_slot('/other', {'x-portal-navigasi': '1'}, **options) is None


async def test_diagnostics_never_keep_query_values_unknown_paths_or_header_secrets():
    assert diagnostic_path('/jasa/pelanggan/123?token=not-for-evidence') == '/jasa/pelanggan/:id'
    assert diagnostic_path('/reset/not-for-evidence?user=private') == '/other'
    assert diagnostic_path('/static/asset.js?v=private&nonce=not-for-evidence') == '/static/asset.js'
    sample = diagnostic_headers({'x-pindah': '1', 'cookie': 'not-for-evidence',
        'x-csrf-token': 'not-for-evidence', 'authorization': 'not-for-evidence'})
    assert sample['pindah_1'] and all(type(v) is bool for v in sample.values())
    assert 'not-for-evidence' not in json.dumps(sample)
    assert 'not-for-evidence' not in json.dumps(diagnostic_error(RuntimeError('not-for-evidence')))


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
        gate = ReadGate(slot=slot); active[slot] = gate; all_gates.append(gate); return gate
    list_html, list_data = arm('list-html'), arm('list-data')
    detail_html, detail_data = arm('detail-html'), arm('detail-data')
    writes, errors, bridge_errors = [], [], []
    out = Path(os.environ.get('UJI_PONSEL_OUT') or os.environ.get('DETAIL_OUT') or 'output/ponsel')
    name = ('portal' if pelanggan else 'padiflow') + f'-{engine}-{width}'
    diagnostic = dict(version=1, role_family='customer' if pelanggan else 'staff-superadmin',
        width=width, engine=engine, observation_only=True, routes=[], snapshots=[], dropped_route_events=0)
    probe_start = time.monotonic()
    def route_event(phase, **values):
        if len(diagnostic['routes']) < 512:
            diagnostic['routes'].append(dict(phase=phase, ms=round((time.monotonic()-probe_start)*1000, 3), **values))
        else:
            diagnostic['dropped_route_events'] += 1
    def save_diagnostic():
        diagnostic['gate_events'] = [dict(number=i+1, slot=g.slot, entered=g.entered.is_set(),
            released=g.release.is_set(), completed=g.completed.is_set()) for i, g in enumerate(all_gates)]
        diagnostic['page_errors'] = [diagnostic_error(e) for e in errors[:16]]
        diagnostic['page_error_count'] = len(errors)
        out.mkdir(parents=True, exist_ok=True)
        (out / (name + '-diagnostic.json')).write_text(json.dumps(diagnostic, indent=2)+'\n')
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
                route_event('request', path=diagnostic_path(u.path), method=req.method,
                            navigation=req.is_navigation_request())
                if closing or not req.url.startswith(BASE + '/'):
                    route_event('abort-unowned-or-closing', path=diagnostic_path(u.path))
                    return await route.abort()
                if req.method != 'GET':
                    writes.append(u.path); return await route.abort()
                if u.path == '/api/aliran':
                    route_event('synthetic-SSE204', path='/api/aliran')
                    return await route.fulfill(status=204, body='')
                headers = {k.lower(): v for k, v in (await req.all_headers()).items()}
                slot = read_slot(u.path, headers, pelanggan=pelanggan, daftar=daftar, detail=detail)
                held = active.get(slot)
                route_event('negotiated', path=diagnostic_path(u.path), slot=slot,
                    headers=diagnostic_headers(headers), gate=all_gates.index(held)+1 if held else None)
                # Forward the request's actual negotiated read shape. A shell
                # must never stand in for a fresh data response on refresh.
                native = {k: v for k, v in headers.items() if k in {
                    'x-pindah', 'x-kerangka-halaman', 'x-portal-navigasi', 'accept',
                    'sec-fetch-mode', 'sec-fetch-dest', 'sec-fetch-site', 'sec-fetch-user'}}
                job = asyncio.create_task(c.get(u.path + ('?' + u.query if u.query else ''), headers=native))
                pending.add(job)
                try:
                    response = await asyncio.wait_for(asyncio.shield(job), 60)
                    route_event('native-response', path=diagnostic_path(u.path), status=response.status_code,
                        html=response.headers.get('content-type', '').startswith('text/html'),
                        json=response.headers.get('content-type', '').startswith('application/json'))
                    if held:
                        held.entered.set()
                        route_event('gate-entered', slot=slot, gate=all_gates.index(held)+1)
                        await asyncio.wait_for(held.release.wait(), 20)
                        route_event('gate-released', slot=slot, gate=all_gates.index(held)+1)
                    await route.fulfill(status=response.status_code, body=response.content,
                        headers={k: v for k, v in response.headers.items() if k.lower() not in {
                            'content-length', 'content-encoding', 'transfer-encoding', 'set-cookie'}})
                    route_event('fulfilled', path=diagnostic_path(u.path), slot=slot)
                except BrowserError as error:
                    route_event('browser-error', path=diagnostic_path(u.path), error=diagnostic_error(error),
                                request_failed=bool(req.failure))
                    if not closing and not req.failure:
                        bridge_errors.append(type(error).__name__)
                        raise
                except BaseException as error:
                    route_event('bridge-exception', path=diagnostic_path(u.path), error=diagnostic_error(error))
                    raise
                finally:
                    pending.discard(job)
                    if held: held.completed.set()
            await ctx.route('**/*', app)
            page = await ctx.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
            async def snapshot(phase, error=None):
                # No readiness predicate or controller method is invoked. The
                # bounded sample may miss a provisional document: record that
                # gap rather than waiting for navigation/data to become ready.
                row = dict(phase=phase, ms=round((time.monotonic()-probe_start)*1000, 3),
                    page_path=diagnostic_path(page.url), frame_paths=[diagnostic_path(f.url) for f in page.frames[:8]])
                if error is not None: row['error'] = diagnostic_error(error)
                try:
                    row['DOM'] = await asyncio.wait_for(page.evaluate("""() => {
                      const frame=document.querySelector('.bingkai'),main=document.getElementById('isi-halaman')||document.querySelector('main'),
                        registry=document.getElementById('padi-kerangka-langsung');
                      return {readyState:document.readyState,main:!!main,frame:!!frame,
                        staffSessionPresent:!!document.getElementById('formulir-sesi')?.dataset.token,
                        portalSessionPresent:!!document.querySelector('meta[name="formulir-sesi"]')?.content,
                        editorPresent:!!document.querySelector('[data-editor-perintah],[data-kemas-ulang]'),
                        PINDAH:!!window.PINDAH,UIFactory:typeof window.PadiKerangkaUI?.buat==='function',
                        UIData:!!window.PadiKerangkaUIData,JasaDetailFactory:typeof window.PadiKerangkaJasaDetailUI?.buat==='function',
                        PortalFactory:typeof window.PadiKerangkaPortalUI?.buat==='function',
                        PortalDetailFactory:typeof window.PadiKerangkaPortalDetailUI?.buat==='function',
                        registryPresent:!!registry,registryBytes:registry?.textContent.length||0,
                        UIBindingPresent:!!document.getElementById('padi-kerangka-ui'),
                        JasaDetailBindingPresent:!!document.getElementById('padi-jasa-detail-catalog'),
                        PortalBindingPresent:!!document.getElementById('padi-portal-kerangka'),
                        PortalDetailBindingPresent:!!document.getElementById('padi-portal-detail-catalog'),
                        genericLoading:!!document.querySelector('.halaman-memuat'),
                        intakePending:!!document.querySelector('[data-bm-page][data-bm-shell]'),
                        jasaPending:!!document.querySelector('[data-jasa-bertahap]'),
                        jasaDetailPending:!!document.querySelector('[data-jasa-detail-kerangka]'),
                        portalPending:!!document.querySelector('[data-portal-native-frame]'),
                        portalDetailPending:!!document.querySelector('[data-portal-detail-frame]')};
                    }"""), .75)
                except BaseException as probe_error:
                    row['DOM_unavailable'] = type(probe_error).__name__
                row['completed_ms'] = round((time.monotonic()-probe_start)*1000, 3)
                if len(diagnostic['snapshots']) < 16: diagnostic['snapshots'].append(row)
                save_diagnostic()
            await page.add_init_script("document.addEventListener('click',e=>{let a=e.target.closest('a[href]');if(a){window.taps=window.taps||{};window.taps[a.pathname]=(window.taps[a.pathname]||0)+1;window.lastTap=performance.now();}},true);")
            async def refresh_native():
                await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))" if pelanggan
                                    else 'PINDAH.muatPerubahan()')
            try:
                await page.goto(BASE + asal)
                await page.locator(buka).tap()
                await snapshot('before-list-click')
                await page.locator(menu + f' a[href="{daftar}"]').first.tap()
                await snapshot('after-list-click')
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
                await snapshot('before-detail-click')
                await page.locator('main a[href="' + detailHref + '"]').first.tap()
                await snapshot('after-detail-click')
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
                out.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(out / (name + '.png')))
                (out / (name + '.json')).write_text(json.dumps(dict(engine=engine, width=width, touch=True,
                    sidebar_taps=taps[daftar], detail_taps=taps[detail], independently_held_HTML_and_native_data=True,
                    old_list_response_ignored=True, menu_preserved=True, input_preserved=True,
                    scroll_preserved=True, measured_scroll_top=top, errors=errors, writes=writes)) + '\n')
                await page.go_back(); await expect(page).to_have_url(BASE + daftar)
                await expect(page.locator('.halaman-memuat')).to_have_count(0, timeout=10000)
            except BaseException as error:
                await snapshot('exception', error)
                raise
            finally:
                closing = True
                for gate in all_gates: gate.release.set()
                if pending:
                    await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 65)
                await ctx.close(); await browser.close()
                save_diagnostic()
        assert await _sidik(pg) == before
