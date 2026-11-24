"""Prepared owner acceptance, not a PG/browser execution receipt.

Native fixture/auth/readers supply every business value. The browser uses the
existing ASGI bridge with service workers blocked. A held X1/0 native HTML GET
is the data phase: the destination frame must already exist without that HTML.
Explicit document GET checks below cover the separate server-document protocol;
they are not a real HTTP responseStart, browser-cache or PWA acceptance test.

No browser POST, stock change, new fixture role/binding or fake PDF response is
used. Setup is the existing approved fixture recipes, before fingerprints.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect

from tests.pg.test_barang_keluar import gudang, _klien as existing_client, _perintah
from tests.pg.test_barang_masuk_bertahap_browser import BASE, peramban
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_riwayat_giling import _klien as role_client
from tests.pg.test_riwayat_giling_desain_browser import selesai as giling_selesai
from tests.pg.test_form_hasil_penggilingan import hasil, g1
from tests.pg.test_riwayat_sosoh_desain_browser import riwayat as sosoh_selesai
from tests.pg.test_koreksi_bahan_berjalan import running, dunia
from tests.pg.test_riwayat_pengeringan_desain_browser import riwayat as dryer_selesai
from tests.pg.test_detail_pendinginan_tab import pendingin, dryer_tab, pengeringan, dryer_pabrik

pytestmark = pytest.mark.asyncio
NATIVE = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
DOCUMENT = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}


def chrome(html):
    """Semantic golden is always the actual native response, never the shell."""
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    assert main and doc.title
    bar = main.select_one('header.bar')
    crumb = main.select_one('.desktop-chrome__crumbrow')
    assert bar and crumb
    brand = bar.select_one('.bar__merek')
    control = bar.select_one('.bar__menu,.bar__balik')
    assert brand and control
    trail = []
    for li in crumb.select('nav.desktop-breadcrumb ol > li'):
        item = li.select_one('a[href],[aria-current="page"]')
        assert item
        trail.append((item.name, item.get_text(' ', strip=True), item.get('href'), item.get('aria-current')))
    return dict(title=doc.title.get_text(), brand=brand.get_text(' ', strip=True),
                brand_label=brand.get('aria-label'), brand_href=brand.get('href'),
                control=dict(tag=control.name, href=control.get('href'),
                             label=control.get('aria-label'), id=control.get('id')),
                crumbs=trail,
                h1=[n.get_text(' ', strip=True) for n in main.select('h1')])


def read_gate(transport, path):
    entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    transport['gate_headers'][path] = {'x-pindah': '1', 'x-kerangka-halaman': '0'}
    transport['gates'][path] = entered, release
    transport['completed'][path] = completed
    return entered, release, completed


async def two_frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def muatan_storage(page):
    # The exact native controller's persisted draft/pending namespace. Do not
    # confuse the SDK's unrelated reference cache write with a draft mutation.
    return await page.evaluate('()=>Object.fromEntries(Object.entries(sessionStorage).filter(([key])=>key.startsWith("lembar-muatan-v1:")))')


async def performance_probe(page):
    await page.add_init_script('''(() => {
      const report={supported:false,longtasks:[]};window.__ownerReadPerformance=report;
      if(typeof PerformanceObserver==='function'&&PerformanceObserver.supportedEntryTypes?.includes('longtask')){
        report.supported=true;new PerformanceObserver(list=>{
          for(const e of list.getEntries())report.longtasks.push({start:e.startTime,duration:e.duration});
        }).observe({type:'longtask',buffered:true});
      }
    })()''')


async def evidence(page, name, *, native, phase, extra=None):
    target = os.environ.get('DETAIL_OUT')
    if not target:
        return
    out = Path(target) / name
    out.mkdir(parents=True, exist_ok=True)
    html = await page.content()
    metrics = await page.evaluate('''()=>({
      observer:window.__ownerReadPerformance||{supported:false,longtasks:[]},
      navigation:performance.getEntriesByType('navigation').map(e=>({type:e.type,responseStart:e.responseStart,domInteractive:e.domInteractive,duration:e.duration})),
      resources:performance.getEntriesByType('resource').map(e=>({path:new URL(e.name).pathname,kind:e.initiatorType,duration:e.duration,bytes:e.transferSize}))
    })''')
    value = dict(phase=phase, native_document_bytes=len(native.encode()),
                 native_document_gzip_bytes=len(gzip.compress(native.encode(), mtime=0)),
                 current_browser_html_bytes=len(html.encode()),
                 current_browser_html_gzip_bytes=len(gzip.compress(html.encode(), mtime=0)),
                 browser_metrics=metrics, transport='intercepted-browser-to-in-process-ASGI',
                 real_server_responseStart=False, performance_comparison=False,
                 note='Observations only; no dense/cold-cache or latency benchmark claim.', **(extra or {}))
    (out / (phase + '.json')).write_text(json.dumps(value, indent=2))
    await page.screenshot(path=str(out / (phase + '.png')), full_page=True)


async def sidebar_link(page, target, width):
    if width < 900:
        button = page.locator('#buka-laci')
        await expect(button).to_be_visible()
        await button.click()
    link = page.locator('#laci a[href="' + target + '"]:visible')
    assert await link.count() == 1, 'Canonical target must be actually offered by the native current menu.'
    return link


async def leave_native(page, width):
    """Choose a currently visible native control, never insert a test link."""
    if width < 900:
        menu = page.locator('#buka-laci')
        if await menu.count() and await menu.is_visible():
            await menu.click()
        else:
            back = page.locator('#isi-halaman header.bar a.bar__balik')
            await expect(back).to_be_visible()
            target = await back.get_attribute('href')
            assert target and target.startswith('/')
            await back.press('Enter')
            await expect(page).to_have_url(BASE + target)
            return target
    link = page.locator('#laci a[href="/kabar"]:visible')
    assert await link.count() == 1
    await link.press('Enter')
    await expect(page).to_have_url(BASE + '/kabar')
    return '/kabar'


@pytest.mark.parametrize('role', ['admin', 'operator'])
@pytest.mark.parametrize('width', [390, 1280])
async def test_home_actual_menu_first_paint_native_parity_and_late_leave(pg, gudang, role, width):
    async with await role_client(pg, peran=role, gudang='Gudang 2') as client:
        native = await client.get('/', headers=NATIVE)
        assert native.status_code == 200
        expected = chrome(native.text)
        # Explicit document protocol proves the server returns structure rather
        # than the generic transition. ASGI browser page.goto lacks Sec-Fetch.
        document = await client.get('/', headers=DOCUMENT)
        assert document.status_code == 200 and 'data-beranda-native' in document.text
        assert chrome(document.text) == expected
        before = await _sidik(pg)
        async with peramban(client, width) as (page, transport):
            await performance_probe(page)
            await page.goto(BASE + '/kabar', wait_until='load')
            await page.wait_for_function('()=>window.PadiKerangkaBerandaUI&&document.getElementById("padi-beranda-kerangka")')
            entered, release, done = read_gate(transport, '/')
            # Existing bridge pads only an already-authorized actual native
            # read. This is a bounded-size rejection/retry control, not a
            # claim that the server returned an outage or changed business data.
            transport['pad_html']['/'] = 8 * 1024 * 1024
            try:
                await (await sidebar_link(page, '/', width)).press('Enter')
                await asyncio.wait_for(entered.wait(), 20)
                shell = page.locator('[data-beranda-native]')
                await expect(shell).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert chrome(await page.content()) == expected
                for label in ('Perlu perhatian', 'Sedang berjalan', 'Ringkasan operasional'):
                    await expect(shell.locator('[aria-label="' + label + '"]')).to_be_visible()
                assert await shell.locator('form,input,select,textarea,[data-kirim],[data-post]').count() == 0
                await evidence(page, 'home-' + role + '-' + str(width), native=native.text, phase='before-data')
                release.set()
                retry = shell.locator('[data-home-native-retry]')
                await expect(retry).to_be_visible(timeout=20000)
                await expect(shell.locator('[data-home-native-status]')).to_contain_text('Dokumen terlalu besar')
                assert chrome(await page.content()) == expected
                await retry.press('Enter')
                await expect(shell).to_have_count(0, timeout=20000)
                assert chrome(await page.content()) == expected
                await expect(page.locator('#judul-beranda')).to_have_text(expected['h1'][0])
                await expect(page.locator('#judul-beranda')).to_be_focused()
                await evidence(page, 'home-' + role + '-' + str(width), native=native.text, phase='after-data')
                # Re-enter from an actual native menu, then leave while the
                # second fresh GET is still held. Old HTML cannot replace it.
                await page.goto(BASE + '/kabar', wait_until='load')
                entered2, release2, done2 = read_gate(transport, '/')
                try:
                    await (await sidebar_link(page, '/', width)).press('Enter')
                    await asyncio.wait_for(entered2.wait(), 20)
                    await expect(shell).to_be_visible()
                    target = await leave_native(page, width)
                    release2.set()
                    await asyncio.wait_for(done2.wait(), 20)
                    await two_frames(page)
                    await expect(page).to_have_url(BASE + target)
                    await expect(shell).to_have_count(0)
                finally:
                    release2.set()
                assert not transport['posts'] and not transport['errors'], transport
            finally:
                release.set()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280])
async def test_muatan_operator_actual_menu_inert_fields_then_native_controller(pg, gudang, width):
    # Existing perintah recipe; no muat/finish/verify POST is sent in the test.
    await _perintah(pg, gudang, karung=40)
    async with await existing_client(pg, gudang['op'], 'owner-frame-muatan', mode='operator') as client:
        native = await client.get('/muatan', headers=NATIVE)
        assert native.status_code == 200
        expected = chrome(native.text)
        document = await client.get('/muatan', headers=DOCUMENT)
        assert document.status_code == 200 and 'data-muatan-native' in document.text
        assert chrome(document.text) == expected
        before = await _sidik(pg)
        async with peramban(client, width) as (page, transport):
            await performance_probe(page)
            await page.goto(BASE + '/kabar', wait_until='load')
            await page.wait_for_function('()=>window.PadiKerangkaMuatanUI&&document.getElementById("padi-muatan-kerangka")')
            storage = await muatan_storage(page)
            entered, release, done = read_gate(transport, '/muatan')
            try:
                await (await sidebar_link(page, '/muatan', width)).press('Enter')
                await asyncio.wait_for(entered.wait(), 20)
                shell = page.locator('[data-muatan-native]')
                await expect(shell).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert chrome(await page.content()) == expected
                assert await shell.locator('thead th').all_text_contents() == ['Barang', 'Perintah', 'Total dimuat', 'Status sisa belum dibaca']
                for label in ('Muat semua sesuai perintah', 'Muatan berbeda dari perintah'):
                    await expect(shell.get_by_role('button', name=label, exact=True)).to_be_disabled()
                assert await shell.locator('form,input,select,textarea,[data-editor-perintah],[data-lembar-muatan],#lembar-awal').count() == 0
                assert await muatan_storage(page) == storage
                await evidence(page, 'muatan-operator-' + str(width), native=native.text, phase='before-data')
                release.set()
                await expect(shell).to_have_count(0, timeout=20000)
                await expect(page.locator('[data-lembar-muatan]')).to_be_visible()
                assert chrome(await page.content()) == expected
                await expect(page.locator('#lembar-awal')).to_have_count(1)
                assert await page.locator('script[src*="/muat-ringkas.js"]').count() == 1
                await evidence(page, 'muatan-operator-' + str(width), native=native.text, phase='after-data')
                # A delayed second native read must not restore the editor or
                # consume pending/draft keys after a currently visible menu
                # control has navigated away.
                await page.goto(BASE + '/kabar', wait_until='load')
                await page.wait_for_function('()=>window.PadiKerangkaMuatanUI&&document.getElementById("padi-muatan-kerangka")')
                stored = await muatan_storage(page)
                entered2, release2, done2 = read_gate(transport, '/muatan')
                try:
                    await (await sidebar_link(page, '/muatan', width)).press('Enter')
                    await asyncio.wait_for(entered2.wait(), 20)
                    await expect(shell).to_be_visible()
                    assert await muatan_storage(page) == stored
                    target = await leave_native(page, width)
                    release2.set()
                    await asyncio.wait_for(done2.wait(), 20)
                    await two_frames(page)
                    await expect(page).to_have_url(BASE + target)
                    await expect(page.locator('[data-muatan-native],[data-lembar-muatan]')).to_have_count(0)
                finally:
                    release2.set()
                assert not transport['posts'] and not transport['errors'], transport
            finally:
                release.set()
        assert await _sidik(pg) == before


async def test_muatan_admin_document_remains_readonly_without_inventing_menu_offer(pg, gudang):
    async with await role_client(pg, peran='admin', gudang='Gudang 2') as client:
        before = await _sidik(pg)
        native = await client.get('/muatan', headers=NATIVE)
        response = await client.get('/muatan', headers=DOCUMENT)
        assert native.status_code == response.status_code == 200
        doc = BeautifulSoup(response.text, 'html.parser')
        root = doc.select_one('[data-muatan-native]')
        assert root and chrome(response.text) == chrome(native.text)
        assert not root.select('.mr-actions,form,input,select,textarea,[data-editor-perintah],#lembar-awal')
        assert 'Akses baca saja sesuai peran efektif.' in root.get_text()
        assert await _sidik(pg) == before


async def pdf_exercise(pg, client, detail, width, kind):
    """Compare actual native PDF requests, not a fabricated PDF/HTTP oracle."""
    target = detail + '/laporan'
    pdf = target + '.pdf'
    native = await client.get(target, headers=NATIVE)
    assert native.status_code == 200
    expected = chrome(native.text)
    native_doc = BeautifulSoup(native.text, 'html.parser')
    native_frame = native_doc.select_one('#isi-halaman iframe')
    native_heading = native_doc.select_one('#isi-halaman section.kartu h2')
    assert native_frame and native_heading
    expected_frame_title = native_frame.get('title')
    expected_heading = native_heading.get_text(' ', strip=True)
    before = await _sidik(pg)
    # Direct native HTML in a fresh intercepted context: existing iframe plus
    # existing share preparation fetch. Never click Print/share/download.
    async with peramban(client, width) as (page, transport):
        await performance_probe(page)
        await page.goto(BASE + target, wait_until='load')
        await expect(page.locator('#bagikan-pdf')).to_be_enabled(timeout=30000)
        await expect(page.locator('#status-bagikan')).to_contain_text('PDF siap')
        await page.wait_for_load_state('networkidle')
        baseline_reads = transport['gets'].count(pdf)
        assert baseline_reads >= 1, 'Actual binary PDF path must be requested; no mocked PDF.'
        await evidence(page, 'pdf-' + kind + '-' + str(width), native=native.text,
                       phase='native-document-control', extra={'pdf_get_count': baseline_reads})
        assert not transport['posts'] and not transport['errors'], transport
    async with peramban(client, width) as (page, transport):
        await performance_probe(page)
        await page.goto(BASE + detail, wait_until='load')
        await page.wait_for_function('()=>window.PadiKerangkaProsesPDFUI&&document.getElementById("padi-proses-pdf-catalog")')
        links = page.locator('.rhs-actions > a[href="' + target + '"]:visible')
        assert await links.count() == 1, 'PDF must be offered by the current actual authorized detail.'
        entered, release, done = read_gate(transport, target)
        try:
            await links.press('Enter')
            await asyncio.wait_for(entered.wait(), 20)
            shell = page.locator('[data-proses-pdf-kerangka]')
            await expect(shell).to_be_visible()
            await expect(page.locator('.halaman-memuat')).to_have_count(0)
            assert chrome(await page.content()) == expected
            await expect(shell.locator('section.kartu h2')).to_have_text(expected_heading)
            frame = shell.locator('iframe')
            assert await frame.count() == 1 and await frame.get_attribute('src') is None
            await expect(frame).to_have_attribute('title', expected_frame_title)
            assert transport['gets'].count(pdf) == 0, 'Pending frame must not fetch a PDF before the authorized native read is installed.'
            await expect(shell.locator('#bagikan-pdf')).to_be_disabled()
            assert await shell.locator('a[href*=".pdf"]').count() == 0
            await evidence(page, 'pdf-' + kind + '-' + str(width), native=native.text, phase='before-data')
            release.set()
            await expect(shell).to_have_count(0, timeout=20000)
            await expect(page.locator('iframe[data-ppv-activated="1"]')).to_have_attribute('src', pdf)
            await expect(page.locator('#bagikan-pdf')).to_be_enabled(timeout=30000)
            await expect(page.locator('#status-bagikan')).to_contain_text('PDF siap')
            await page.wait_for_load_state('networkidle')
            reads = transport['gets'].count(pdf)
            assert reads == baseline_reads, {'native_pdf_gets': baseline_reads, 'candidate_pdf_gets': reads}
            assert chrome(await page.content()) == expected
            assert await page.locator('a[href="' + pdf + '?unduh=1"]').count() == 1
            await evidence(page, 'pdf-' + kind + '-' + str(width), native=native.text,
                           phase='after-data', extra={'native_pdf_get_count': baseline_reads, 'candidate_pdf_get_count': reads})
            assert not transport['posts'] and not transport['errors'], transport
        finally:
            release.set()
    assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280])
async def test_giling_pdf_actual_detail_link_and_request_count(pg, giling_selesai, width):
    _, process = giling_selesai
    async with await role_client(pg, peran='operator', gudang='Gudang 1') as client:
        await pdf_exercise(pg, client, '/riwayat-giling/' + str(process.id), width, 'giling')


@pytest.mark.parametrize('width', [390, 1280])
async def test_sosoh_pdf_actual_detail_link_and_request_count(pg, sosoh_selesai, width):
    async with await role_client(pg, peran='operator', gudang='Gudang 2') as client:
        await pdf_exercise(pg, client, '/riwayat-sosoh/' + str(sosoh_selesai['id']), width, 'sosoh')


@pytest.mark.parametrize('width', [390, 1280])
async def test_dryer_pdf_actual_detail_link_and_request_count(pg, dryer_selesai, width):
    async with await role_client(pg, peran='operator', gudang='Gudang 1') as client:
        await pdf_exercise(pg, client, '/riwayat-pengeringan/' + str(dryer_selesai['id']), width, 'pengeringan')
