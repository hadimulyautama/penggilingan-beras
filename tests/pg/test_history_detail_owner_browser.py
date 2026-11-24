"""PROPOSAL owner acceptance; not run and not installed in product tests yet.

Integrator adopts this exact file into tests/pg after its current freeze. The
existing native recipes create only disposable fixture data BEFORE fingerprints.
Browser traffic afterwards must be GET-only. peramban uses in-process ASGI,
service_workers=block: this is not PWA, real Safari, hosted or production proof.
No skips or optional success paths are added; unsupported source must fail.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect

from app.models import MillingProcess
from tests.pg.test_barang_masuk_bertahap_browser import BASE, peramban
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_riwayat_giling import _klien
# Fixture aliases isolate three fixtures originally named riwayat. Their own
# dependency names remain imported, not copied into a new dummy domain recipe.
from tests.pg.test_riwayat_giling_desain_browser import selesai as giling_selesai
from tests.pg.test_form_hasil_penggilingan import hasil, g1
from tests.pg.test_riwayat_sosoh_desain_browser import riwayat as sosoh_selesai
from tests.pg.test_koreksi_bahan_berjalan import running, dunia
from tests.pg.test_riwayat_pengeringan_desain_browser import riwayat as dryer_selesai
from tests.pg.test_detail_pendinginan_tab import pendingin, dryer_tab, pengeringan, dryer_pabrik
from tests.pg.test_riwayat_qc_detail import qc as qc_native
from tests.pg.test_qc_sosoh import dunia as rice_world, ambil

pytestmark = pytest.mark.asyncio
NATIVE = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
DOC = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
SHELL = '[data-riwayat-detail-native]'
READY = '[data-riwayat-detail-native-isi]'


def title_and_chrome(html):
    """Golden from real native GET; no generic heading or guessed icon oracle."""
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    assert main is not None
    bar = main.select_one('header.bar')
    crumbs = main.select_one('.desktop-chrome__crumbrow nav.desktop-breadcrumb')
    assert bar is not None and crumbs is not None
    brand = bar.select_one('.bar__merek')
    control = bar.select_one('.bar__menu,.bar__balik')
    assert brand is not None and control is not None
    trail = []
    for li in crumbs.select('ol > li'):
        leaf = li.select_one('a[href],[aria-current=page]')
        assert leaf is not None
        trail.append(dict(tag=leaf.name, text=leaf.get_text(' ', strip=True),
                          href=leaf.get('href'), current=leaf.get('aria-current')))
    back = main.select_one('.desktop-chrome__crumbrow a.desktop-back')
    assert back is not None
    body_back = main.select_one('.rhs-back,.riwayat-detail__back')
    return dict(title=doc.title.get_text(), brand=brand.get_text(' ', strip=True),
                brand_label=brand.get('aria-label'),
                control=dict(tag=control.name, href=control.get('href'),
                             classes=control.get('class'), label=control.get('aria-label'),
                             id=control.get('id')),
                crumbs=trail, back=dict(href=back.get('href'), label=back.get('aria-label')),
                h1=[n.get_text(' ', strip=True) for n in main.select('h1')],
                # Intentionally strict: known generic History shell back text
                # must not silently be accepted as native parity.
                body_back=None if body_back is None else dict(
                    href=body_back.get('href'), text=body_back.get_text(' ', strip=True)))


def headers(html):
    doc = BeautifulSoup(html, 'html.parser')
    root = doc.select_one('#isi-halaman')
    assert root is not None
    # Native controllers may move a whole QC table between panels. Preserve
    # each table's column order, compare groups without mistaking that move
    # for changed columns. No values/row DTOs are used as a shape oracle.
    groups = []
    for head in root.select('thead,.riwayat-detail__table-head'):
        columns = [n.get_text(' ', strip=True) for n in head.select('th' if head.name == 'thead' else ':scope > span')]
        if columns:
            groups.append(tuple(columns))
    return sorted(groups)


def gate(transport, path):
    entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    transport['gate_headers'][path] = {'x-pindah': '1', 'x-kerangka-halaman': '0'}
    transport['gates'][path] = (entered, release)
    transport['completed'][path] = completed
    return entered, release, completed


async def two_frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def native_golden(client, address):
    response = await client.get(address, headers=NATIVE)
    assert response.status_code == 200, (address, response.status_code)
    assert not BeautifulSoup(response.text, 'html.parser').select(SHELL)
    return response.text


async def source_ready(page, source):
    await page.goto(BASE + source, wait_until='load')
    await page.wait_for_function("""()=>{
      const f=document.querySelector('.bingkai'),t=document.getElementById('formulir-sesi')?.dataset.token;
      return window.PadiKerangkaRiwayatDetailUI&&f&&t&&
        window.PadiKerangkaRiwayatDetailUI.currentCatalog(f.dataset.pindahKonteks,document.documentElement.dataset.versi,t);
    }""")


async def actual_link(page, target, code, family):
    selector = '[data-daftar-riwayat-proses]' if family == 'history' else '[data-riwayat-qc]'
    link = page.locator(selector + ' a[href="' + target + '"]:visible').filter(has_text=code)
    await expect(link).to_have_count(1)
    return link


async def open_from_actual_row(page, transport, client, item, *, summary=False):
    source, path, code, family = (item[k] for k in ('source', 'path', 'code', 'family'))
    await source_ready(page, source)
    link = await actual_link(page, path, code, family)
    original = BeautifulSoup(await native_golden(client, source), 'html.parser')
    matches = [a for a in original.select('a[href]') if a.get('href') == path and code in a.get_text()]
    assert matches, 'Current native source must supply this exact href/code'
    diagnostic = await page.evaluate("""target=>{
      const frame=document.querySelector('.bingkai'),token=document.getElementById('formulir-sesi')?.dataset.token,
       cap=document.documentElement.dataset.versi,host=document.getElementById('padi-kerangka-langsung');
      try{
       const r=JSON.parse(host.textContent),base=r.frames['/barang-masuk'].map(i=>r.potongan[i]).join(''),
        f=window.PadiKerangkaRiwayatDetailUI.buat(target,base,frame.dataset.pindahKonteks,cap,token);
       return {factory:!!f,menu:!!document.getElementById('padi-riwayat-kerangka'),source:location.pathname+location.search};
      }catch(e){return {error:String(e)};}
    }""", path)
    assert diagnostic.get('factory'), diagnostic
    entered, release, completed = gate(transport, path)
    if summary:
        original_summary = next((a.find_parent('summary') for a in matches if a.find_parent('summary')), None)
        assert original_summary is not None and 'location.href=' in original_summary.get('onclick', '')
        current_summary = link.locator('xpath=ancestor::summary[1]')
        await expect(current_summary).to_have_count(1)
        assert await current_summary.get_attribute('onclick') is None
        await current_summary.press('Enter')
    else:
        if any('location.href=this.href' in a.get('onclick', '') for a in matches):
            assert await link.get_attribute('onclick') is None
        await link.press('Enter')
    await asyncio.wait_for(entered.wait(), 20)
    await expect(page.locator(SHELL)).to_be_visible()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    return release, completed


async def assert_native_parity(page, golden, *, before_data):
    actual = title_and_chrome(await page.content())
    expected = title_and_chrome(golden)
    assert actual == expected, dict(before_data=before_data, actual=actual, expected=expected)
    # Dynamic source rows/values may appear only after read; no invented table
    # is required for QC variants whose native detail has no table.
    actual_columns, native_columns = headers(await page.content()), headers(golden)
    if before_data:
        if native_columns:
            assert actual_columns, 'Native tables cannot be replaced by a loading sentence'
        # Conditional nested data tables may only be known after fresh read.
        # Every table advertised before that read must already be native.
        assert all(columns in native_columns for columns in actual_columns), (actual_columns, native_columns)
    else:
        assert actual_columns == native_columns


async def proof(pg, client, item, width, monkeypatch, *, summary=False, edges=False, dirty=False):
    """One scoped actual record; no success DTO, identity or writer is mocked."""
    client.base_url = BASE
    path = item['path']
    golden = await native_golden(client, path)
    source_golden = await native_golden(client, item['source'])
    assert item['code'] in source_golden
    trace, fault = [], {'next': None, 'count': 0}
    original_request = client.request

    async def request(method, url, **kwargs):
        response = await original_request(method, url, **kwargs)
        path_in = urlsplit(str(url)).path
        request_headers = {k.lower(): v for k, v in kwargs.get('headers', {}).items()}
        is_data = method.upper() == 'GET' and path_in == path and request_headers.get('x-pindah') == '1' and request_headers.get('x-kerangka-halaman') == '0'
        trace.append(dict(method=method.upper(), path=path_in, native=is_data,
                          document=request_headers.get('sec-fetch-dest') == 'document'))
        if is_data and fault['next']:
            assert response.status_code == 200
            mode, fault['next'] = fault['next'], None
            fault['count'] += 1
            if mode == '503':
                return httpx.Response(503, text='Owner fixture read unavailable',
                    headers={'content-type': 'text/html'}, request=response.request)
            assert mode == 'context'
            body = response.text
            import re
            changed, count = re.subn(r'data-pindah-konteks="[^"]+"', 'data-pindah-konteks="owner-stale-context"', body, count=1)
            assert count == 1
            return httpx.Response(200, text=changed,
                headers={'content-type': 'text/html'}, request=response.request)
        return response

    monkeypatch.setattr(client, 'request', request)
    before = await _sidik(pg)
    releases = []
    out = Path(os.environ['DETAIL_OUT']) / ('history-' + item['name'] + '-' + str(width)) if os.environ.get('DETAIL_OUT') else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    async with peramban(client, width) as (page, transport):
        try:
            release, completed = await open_from_actual_row(page, transport, client, item, summary=summary)
            releases.append(release)
            root = page.locator(SHELL)
            await assert_native_parity(page, golden, before_data=True)
            assert not await root.locator('form[method=post],input[name=_csrf]').count()
            assert not await root.locator('input:not(:disabled),textarea:not(:disabled),select:not(:disabled)').count()
            assert await root.locator('[data-rdn-status]').count() == 1
            if out:
                await page.screenshot(path=str(out / 'before-data.png'), full_page=True)
            # Keep the fresh data pending while the real local guide is open;
            # hydrate must wait, preserve dialog/focus, then restore native guide.
            guide_button = root.locator('[data-rdn-guide]:visible').first
            if await guide_button.count() == 0:
                guide_button = page.locator('[data-lk-buka="rdn-panduan"]:visible').first
            await guide_button.focus()
            await page.keyboard.press('Enter')
            await expect(page.locator('#rdn-panduan')).to_be_visible()
            release.set()
            await asyncio.wait_for(completed.wait(), 20)
            await expect(root).to_have_attribute('data-padi-baca-native-state', 'waiting-interaction')
            await expect(page.locator('#rdn-panduan')).to_be_visible()
            await page.keyboard.press('Escape')
            await expect(root).to_have_count(0, timeout=20000)
            await expect(page.locator(READY)).to_be_visible()
            await assert_native_parity(page, golden, before_data=False)
            assert await page.locator(':focus').get_attribute('data-lk-buka') is not None
            if out:
                await page.screenshot(path=str(out / 'after-data.png'), full_page=True)
            # The pilot must not fetch an HTML document before rendering its
            # public shape: all target reads so far were native X-Pindah GETs.
            assert not [x for x in trace if x['path'] == path and x['document']], trace
            assert not transport['posts'] and not transport['errors'], transport

            if edges:
                for failure in ('503', 'context'):
                    fault['next'] = failure
                    release, _ = await open_from_actual_row(page, transport, client, item, summary=summary)
                    releases.append(release)
                    root = page.locator(SHELL)
                    tabs = root.locator('[data-rdn-tab]')
                    await tabs.nth(0).focus()
                    await page.keyboard.press('ArrowRight')
                    selected = await root.locator('[data-rdn-tab][aria-selected=true]').get_attribute('data-rdn-tab')
                    assert selected != await tabs.nth(0).get_attribute('data-rdn-tab')
                    release.set()
                    retry = root.locator('[data-rdn-retry]')
                    await expect(retry).to_be_visible()
                    await expect(root.locator('[data-rdn-status]')).to_have_attribute('role', 'alert')
                    await expect(root.locator('[data-rdn-tab="' + selected + '"]')).to_have_attribute('aria-selected', 'true')
                    assert not transport['posts']
                    await retry.focus()
                    await page.keyboard.press('Enter')
                    await expect(root).to_have_count(0, timeout=20000)
                    await expect(page.locator(READY)).to_be_visible()
                    # Local tab state must survive explicit read-only retry.
                    selected_native = page.locator(READY + ' [role=tab][aria-selected=true]')
                    assert (await selected_native.get_attribute('aria-controls')).endswith('panel-' + selected)
                    assert await selected_native.evaluate('node=>node===document.activeElement')
                assert fault['count'] == 2

                # Late native data cannot reinsert a closed detail after one
                # keyboard Back link. Complete the intercepted response by
                # explicit barrier release, not sleep-based timing.
                release, completed = await open_from_actual_row(page, transport, client, item, summary=summary)
                releases.append(release)
                root = page.locator(SHELL)
                await root.locator('.rhs-back,.riwayat-detail__back').press('Enter')
                await page.wait_for_function('(path)=>location.pathname===path', arg=item['source'])
                release.set()
                await asyncio.wait_for(completed.wait(), 20)
                await two_frames(page)
                await expect(page.locator(SHELL + ',' + READY)).to_have_count(0)
                assert not transport['posts']

                # Direct bookmark/refresh negotiates the same scoped shell,
                # and browser Back returns to the source without writes.
                await page.goto(BASE + item['source'], wait_until='load')
                entered, release, completed = gate(transport, path)
                releases.append(release)
                await page.goto(BASE + path, wait_until='domcontentloaded')
                await asyncio.wait_for(entered.wait(), 20)
                await assert_native_parity(page, golden, before_data=True)
                release.set()
                await expect(page.locator(SHELL)).to_have_count(0, timeout=20000)
                await assert_native_parity(page, golden, before_data=False)
                await page.reload(wait_until='load')
                await expect(page.locator(READY)).to_be_visible()
                await assert_native_parity(page, golden, before_data=False)
                await page.go_back(wait_until='load')
                await page.wait_for_function('(path)=>location.pathname===path', arg=item['source'])
                assert not transport['posts']

            if dirty:
                # Existing Admin inline correction only; never preview/submit.
                # This checks preservation through read-only guide interaction,
                # not adoption of new correction rules or unsaved-nav policy.
                await page.goto(BASE + path, wait_until='load')
                await expect(page.locator(READY)).to_be_visible()
                editor = page.locator('[data-rhs-edit]:visible').first
                await editor.click()
                field = page.locator('[name=hasil_pk]')
                await field.fill('5800')
                await page.locator('[name=alasan]').fill('Draft sintetis tidak disimpan')
                guide = page.locator('[data-lk-buka]:visible').first
                await guide.click()
                await expect(page.locator('dialog[open]')).to_be_visible()
                await page.keyboard.press('Escape')
                await expect(field).to_have_value('5800')
                await expect(page.locator('[name=alasan]')).to_have_value('Draft sintetis tidak disimpan')
                assert not transport['posts']
            assert not transport['posts'] and not transport['errors'], transport
        finally:
            for release in releases:
                release.set()
    assert await _sidik(pg) == before
    if out:
        (out / 'read-trace.json').write_text(json.dumps(trace, indent=2))


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
async def test_history_giling_native_titles_guide_edges_and_readonly_draft(pg, giling_selesai, width, role, monkeypatch):
    _, process = giling_selesai
    async with pg() as db:
        stored = await db.get(MillingProcess, process.id)
        item = dict(name='giling-' + role, path='/riwayat-giling/' + str(stored.id),
                    code=stored.kode_proses, source='/riwayat-giling', family='history')
    async with await _klien(pg, peran=role, gudang='Gudang 1') as client:
        await proof(pg, client, item, width, monkeypatch, edges=width == 1280, dirty=role == 'admin')


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
async def test_history_sosoh_actual_code_and_inline_summary_navigation(pg, sosoh_selesai, width, role, monkeypatch):
    item = dict(name='sosoh-' + role, path='/riwayat-sosoh/' + str(sosoh_selesai['id']),
                code=sosoh_selesai['kode'], source='/riwayat-sosoh', family='history')
    async with await _klien(pg, peran=role, gudang='Gudang 2') as client:
        await proof(pg, client, item, width, monkeypatch, summary=width == 390)


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
async def test_history_dryer_completed_timestamp_native_title_and_summary(pg, dryer_selesai, width, role, monkeypatch):
    item = dict(name='pengeringan-' + role, path='/riwayat-pengeringan/' + str(dryer_selesai['id']),
                code=dryer_selesai['kode'], source='/riwayat-pengeringan', family='history')
    async with await _klien(pg, peran=role, gudang='Gudang 1') as client:
        await proof(pg, client, item, width, monkeypatch, summary=width == 390)


@pytest.mark.parametrize('kind,reference,width,role,warehouse', [
    ('gabah-basah', 'GB-QC-BASAH', 1280, 'admin', 'Gudang 1'),
    ('gabah-kering', 'GB-QC-KERING', 390, 'operator', 'Gudang 1'),
    ('pk-luar', 'PKB-QC-DETAIL', 390, 'operator', 'Gudang 2'),
    ('pk-hasil-giling', 'LOT-QC-DETAIL', 1280, 'admin', 'Gudang 1'),
], ids=['gabah-basah-admin-desktop','gabah-kering-operator-390','pk-luar-operator-390','pk-hasil-admin-desktop'])
async def test_four_actual_qc_resources_native_headings_and_no_new_authority(pg, qc_native, kind, reference, width, role, warehouse, monkeypatch):
    source = '/riwayat-qc/' + kind
    item = dict(name=kind + '-' + role, path=source + '/' + reference,
                source=source, code=reference, family='qc')
    async with await _klien(pg, peran=role, gudang=warehouse) as client:
        await proof(pg, client, item, width, monkeypatch)


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
async def test_rice_qc_actual_sample_admission_and_detail(pg, rice_world, width, role, monkeypatch):
    await ambil(pg, rice_world)
    # Copy primitives while attached; no detached ORM access after rollback.
    async with pg() as db:
        from app.models import PolishingProcess
        process = await db.get(PolishingProcess, rice_world['proc'].id)
        code = process.kode_proses
    source = '/riwayat-qc/beras-hasil-sosoh'
    item = dict(name='beras-' + role, path=source + '/' + code,
                code=code, source=source, family='qc')
    async with await _klien(pg, peran=role, gudang='Gudang 2') as client:
        await proof(pg, client, item, width, monkeypatch, edges=width == 390)


async def test_native_wrong_warehouse_detail_gate_does_not_emit_shell_or_catalog(pg, sosoh_selesai, qc_native):
    # These are known native role doors, not guessed IDs or a public-regex grant.
    targets = ['/riwayat-sosoh/' + str(sosoh_selesai['id']),
               '/riwayat-qc/pk-luar/PKB-QC-DETAIL']
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as client:
        client.base_url = BASE
        before = await _sidik(pg)
        for target in targets:
            native = await client.get(target, headers=NATIVE)
            document = await client.get(target, headers=DOC)
            assert native.status_code == document.status_code == 403
            assert not BeautifulSoup(document.text, 'html.parser').select(SHELL + ',[data-riwayat-detail-catalog]')
        assert await _sidik(pg) == before
