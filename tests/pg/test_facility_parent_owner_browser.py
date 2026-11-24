"""Prepared owner acceptance for the four parent facility first-click pages.

Not an execution receipt. Existing master/auth recipes only, before fingerprints.
GET-only browser assertions never edit config, click Save or alter a draft.
The established ASGI bridge blocks service workers, so this does not prove PWA,
network responseStart or production. Direct documents intentionally stay native.
"""
from __future__ import annotations

import asyncio

import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect

from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import master, klien
from tests.pg.test_barang_masuk_bertahap_browser import BASE, peramban
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_users_read_owner_browser import ReadPhases, two_frames

pytestmark = pytest.mark.asyncio
TARGETS = ('/pengaturan/gudang', '/pengaturan/silo',
           '/pengaturan/mesin', '/pengaturan/jenis-proses')
NATIVE = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
DOCUMENT = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
SHELL = '[data-fasilitas-parent-kerangka]'
READY = '[data-fasilitas-parent-native-isi]'
HOST = '#padi-fasilitas-parent-kerangka'


def chrome(html):
    """Actual native title/Back/breadcrumb, without unknown row names/counts."""
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    assert main is not None and doc.title is not None
    bar = main.select_one('header.bar')
    assert bar is not None
    brand = bar.select_one('.bar__merek')
    back = bar.select_one('.bar__balik')
    crumb = main.select_one('.desktop-chrome__crumbrow')
    assert brand is not None and back is not None and crumb is not None
    trail = []
    for li in crumb.select('nav.desktop-breadcrumb ol > li'):
        item = li.select_one('a[href],[aria-current=page]')
        assert item is not None
        trail.append((item.name, item.get_text(' ', strip=True),
                      item.get('href'), item.get('aria-current')))
    desktop = crumb.select_one('a.desktop-back')
    assert desktop is not None
    return dict(title=doc.title.get_text(), brand=brand.get_text(' ', strip=True),
                brand_label=brand.get('aria-label'),
                mobile_back=(back.get('href'), back.get('aria-label')),
                trail=trail, desktop_back=(desktop.get('href'), desktop.get('aria-label')),
                h1=[n.get_text(' ', strip=True) for n in main.select('h1')],
                tables=[[n.get_text(' ', strip=True) for n in head.select('th')]
                        for head in main.select('thead')])


def fields(doc, region):
    """Native fixed field labels/types only; never business/config values."""
    result = []
    for label in region.select('label'):
        field = doc.find(id=label.get('for')) if label.get('for') else label.select_one('input,select,textarea')
        if field is None or field.get('type') == 'hidden':
            continue
        text = ' '.join(str(n).strip() for n in label.find_all(string=True, recursive=False)
                        if str(n).strip())
        assert text
        result.append((text, field.name, field.get('type', 'text') if field.name == 'input' else None))
    return result


def fixed_shape(html, target):
    """Match ONLY native unconditional add controls, not fabricated edit rows."""
    doc = BeautifulSoup(html, 'html.parser')
    root = doc.select_one(SHELL) or doc.select_one('#isi-halaman section[data-pengaturan-form]')
    assert root is not None
    regions = []
    if target.endswith('/gudang'):
        card = next(n for n in root.select(':scope > .kartu')
                    if n.select_one('h2') and n.select_one('h2').get_text(strip=True) == 'Tambah gudang')
        regions = [('Tambah gudang', card)]
    elif target.endswith('/silo'):
        for group in root.select(':scope > div'):
            label = group.select_one(':scope > span.lbl')
            if label is None:
                continue
            add = group.select_one(':scope > .grup')
            assert add is not None
            regions.append((label.get_text(' ', strip=True), add))
        assert len(regions) == 2
    else:
        allowed = ['Tambah jenis proses'] if target.endswith('/jenis-proses') else ['Tambah mesin / line', 'Tambah dryer']
        for details in root.select(':scope > details'):
            summary = details.select_one(':scope > summary')
            if summary is not None and summary.get_text(' ', strip=True) in allowed:
                regions.append((summary.get_text(' ', strip=True), details))
        assert [label for label, _ in regions] == allowed
    return [(label, fields(doc, region),
             [b.get_text(' ', strip=True) for b in region.select('button')])
            for label, region in regions]


async def golden(client, target):
    response = await client.get(target, headers=NATIVE)
    assert response.status_code == 200, (target, response.status_code)
    assert not BeautifulSoup(response.text, 'html.parser').select(SHELL)
    return response.text


async def settings(page):
    await page.goto(BASE + '/pengaturan', wait_until='load')
    await page.wait_for_function("""()=>window.PadiKerangkaFasilitasParentUI&&
        document.getElementById('padi-fasilitas-parent-kerangka')&&
        document.querySelector('.pg-pintu[href="/pengaturan/gudang"]')""")
    await expect(page.locator('.halaman-memuat')).to_have_count(0)


async def menu_link(page, target):
    link = page.locator('.pg-pintu[href="' + target + '"]')
    if target.endswith('/jenis-proses'):
        details = page.locator('details.pg-lanjutan').filter(has=link)
        if await details.get_attribute('open') is None:
            await details.locator(':scope > summary').press('Enter')
    await expect(link).to_be_visible()
    return link


async def assert_pending(page, expected, target):
    root = page.locator(SHELL)
    await expect(root).to_be_visible()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    assert chrome(await page.content()) == chrome(expected)
    assert fixed_shape(await page.content(), target) == fixed_shape(expected, target)
    assert await root.locator('form,[name],input[value],input[type=hidden],[data-simpan-alat],[data-pengaturan-form],[data-fasilitas]').count() == 0
    assert await root.locator('input:not(:disabled),select:not(:disabled),textarea:not(:disabled)').count() == 0
    assert await root.locator('button:not(:disabled):not([data-fp-retry])').count() == 0
    assert await root.locator('input[type=checkbox]').evaluate_all(
        "nodes=>nodes.every(n=>!n.checked&&n.getAttribute('aria-checked')==='mixed')")
    assert 'Belum ada ' not in await root.inner_text(), 'Unknown collection must not claim empty'
    return root


async def open_held(page, phases, target, expected):
    html, data = phases.arm(target)
    await (await menu_link(page, target)).press('Enter')
    # Real native HTML response is completed on the server and held as DATA.
    # An HTML-first fallback must fail rather than be mistaken for first-click.
    await asyncio.wait_for(data.entered.wait(), 20)
    root = await assert_pending(page, expected, target)
    assert not html.entered.is_set(), 'Destination HTML-first response must not be required'
    html.release.set()  # Data remains independently held.
    await two_frames(page)
    await assert_pending(page, expected, target)
    return root, data


async def release_data(page, phases, root, data, target, expected):
    data.release.set()
    await asyncio.wait_for(data.finished.wait(), 20)
    await expect(root).to_have_count(0, timeout=20000)
    await expect(page.locator(READY)).to_be_visible()
    assert chrome(await page.content()) == chrome(expected)
    assert fixed_shape(await page.content(), target) == fixed_shape(expected, target)
    assert await page.locator('section[data-pengaturan-form] form').count() > 0
    phases.free()


@pytest.mark.parametrize('width', [390, 1280], ids=['super-390', 'super-desktop'])
async def test_four_native_settings_menu_clicks_two_phases_and_back(pg, master, monkeypatch, width):
    client, _, _ = await klien(pg, P.SUPERADMIN, username='facility_parent_super')
    async with client:
        client.base_url = BASE
        expected = {target: await golden(client, target) for target in TARGETS}
        # The parent strategy is first-click only. A separate native browser
        # DOCUMENT request must still perform the original full reader, not
        # silently claim an early authorised data-free document shortcut.
        for target in TARGETS:
            document = await client.get(target, headers=DOCUMENT)
            assert document.status_code == 200
            native_doc = BeautifulSoup(document.text, 'html.parser')
            assert native_doc.select_one(SHELL) is None
            assert native_doc.select_one('section[data-pengaturan-form] form') is not None
            assert chrome(document.text) == chrome(expected[target])
            assert fixed_shape(document.text, target) == fixed_shape(expected[target], target)
        before = await _sidik(pg)
        phases = ReadPhases(client, monkeypatch)
        async with peramban(client, width) as (page, transport):
            try:
                for target in TARGETS:
                    await settings(page)
                    root, data = await open_held(page, phases, target, expected[target])
                    await release_data(page, phases, root, data, target, expected[target])
                    await page.locator('header.bar a.bar__balik').press('Enter')
                    await page.wait_for_function('()=>location.pathname==="/pengaturan"')
                    await expect(page.locator('.pg-pintu[href="/pengaturan/gudang"]')).to_be_visible()
                    await page.go_back(wait_until='load')
                    await page.wait_for_function('path=>location.pathname===path', arg=target)
                    await expect(page.locator(SHELL)).to_have_count(0)
                    await expect(page.locator('section[data-pengaturan-form]')).to_be_visible()
                    assert chrome(await page.content()) == chrome(expected[target])
                    assert fixed_shape(await page.content(), target) == fixed_shape(expected[target], target)
                assert not transport['posts'] and not transport['errors'], transport['errors']
            finally:
                phases.free()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280], ids=['retry-390', 'retry-desktop'])
async def test_parent_read_failure_retry_keyboard_stale_and_leave(pg, master, monkeypatch, width):
    target = '/pengaturan/mesin'
    client, _, _ = await klien(pg, P.SUPERADMIN, username='facility_retry_super')
    async with client:
        client.base_url = BASE
        expected = await golden(client, target)
        before = await _sidik(pg)
        phases = ReadPhases(client, monkeypatch)
        async with peramban(client, width) as (page, transport):
            try:
                for fault in ('503', 'context'):
                    await settings(page)
                    html, data = phases.arm(target, fault=fault)
                    await (await menu_link(page, target)).press('Enter')
                    await asyncio.wait_for(data.entered.wait(), 20)
                    root = await assert_pending(page, expected, target)
                    data.release.set()
                    await asyncio.wait_for(data.finished.wait(), 20)
                    retry = root.locator('[data-fp-retry]')
                    await expect(retry).to_be_visible()
                    await expect(root.locator('[data-fp-status]')).to_have_attribute('role', 'alert')
                    assert chrome(await page.content()) == chrome(expected)
                    phases.free()
                    html, data = phases.arm(target)
                    await retry.focus()
                    await page.keyboard.press('Enter')
                    await asyncio.wait_for(data.entered.wait(), 20)
                    # Respect a newer user-selected header focus; don't steal it.
                    back = page.locator('header.bar a.bar__balik')
                    await back.focus()
                    await expect(back).to_be_focused()
                    await release_data(page, phases, root, data, target, expected)
                    await expect(back).to_be_focused()
                await settings(page)
                root, data = await open_held(page, phases, target, expected)
                await page.locator('header.bar a.bar__balik').press('Enter')
                await page.wait_for_function('()=>location.pathname==="/pengaturan"')
                await expect(page.locator('.pg-pintu[href="/pengaturan/gudang"]')).to_be_visible()
                data.release.set()
                await asyncio.wait_for(data.finished.wait(), 20)
                await two_frames(page)
                await expect(page.locator(SHELL)).to_have_count(0)
                await expect(page.locator('.pg-pintu[href="/pengaturan/gudang"]')).to_be_visible()
                assert await page.locator('section[data-fasilitas] form').count() == 0
                assert not transport['posts'] and not transport['errors'], transport['errors']
            finally:
                phases.free()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280], ids=['line-390', 'line-desktop'])
async def test_fresh_mesin_native_catalog_to_actual_existing_line(pg, master, monkeypatch, width):
    target = '/pengaturan/mesin'
    client, _, _ = await klien(pg, P.SUPERADMIN, username='facility_line_super')
    async with client:
        client.base_url = BASE
        parent = await golden(client, target)
        actual = BeautifulSoup(parent, 'html.parser')
        link = actual.select_one('[data-fasilitas] .pg-grup a.pg-pintu[href^="/pengaturan/mesin/"]')
        assert link is not None, 'Existing seed_master recipe must provide a real line'
        line_target = link['href']
        expected = await golden(client, line_target)
        before = await _sidik(pg)
        phases = ReadPhases(client, monkeypatch)
        async with peramban(client, width) as (page, transport):
            try:
                await settings(page)
                root, data = await open_held(page, phases, target, parent)
                assert await page.locator('#padi-fasilitas-detail-catalog').count() == 0
                await release_data(page, phases, root, data, target, parent)
                await expect(page.locator('#padi-fasilitas-detail-catalog')).to_have_count(1)
                html, data = phases.arm(line_target)
                native_link = page.locator('[data-fasilitas] .pg-grup a.pg-pintu[href="' + line_target + '"]')
                await expect(native_link).to_be_visible()
                await native_link.press('Enter')
                await asyncio.wait_for(data.entered.wait(), 20)
                detail = page.locator('[data-fasilitas-detail-kerangka]')
                await expect(detail).to_be_visible()
                assert not html.entered.is_set()
                assert chrome(await page.content()) == chrome(expected)
                assert await detail.locator('form,[name],input[type=hidden]').count() == 0
                html.release.set()
                data.release.set()
                await asyncio.wait_for(data.finished.wait(), 20)
                await expect(detail).to_have_count(0, timeout=20000)
                await expect(page.locator('[data-fasilitas-detail-native-isi]')).to_be_visible()
                assert chrome(await page.content()) == chrome(expected)
                assert await page.locator('form[action="/pengaturan/fasilitas"]').count() > 0
                assert not transport['posts'] and not transport['errors'], transport['errors']
            finally:
                phases.free()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('role,warehouse', [(P.ADMIN, None), (P.OPERATOR, 'Gudang 1')], ids=['ordinary-admin', 'operator'])
async def test_active_super_keeps_ordinary_roles_denied_no_parent_catalog(pg, master, role, warehouse):
    # Keep an actual active Super before ordinary Admin is tested; do not
    # accidentally exercise the native no-Super recovery exception.
    supervisor, _, _ = await klien(pg, P.SUPERADMIN, username='facility_guard_super')
    await supervisor.aclose()
    client, _, _ = await klien(pg, role, warehouse, username='facility_guard_ordinary')
    async with client:
        before = await _sidik(pg)
        settings_response = await client.get('/pengaturan', headers=NATIVE)
        assert settings_response.status_code == 200
        home = BeautifulSoup(settings_response.text, 'html.parser')
        assert home.select_one(HOST) is None
        for target in TARGETS:
            assert home.select_one('a[href="' + target + '"]') is None
            for headers in (NATIVE, DOCUMENT):
                response = await client.get(target, headers=headers)
                assert response.status_code == 403, (target, role, response.status_code)
                doc = BeautifulSoup(response.text, 'html.parser')
                assert doc.select_one(SHELL) is None and doc.select_one(HOST) is None
        assert await _sidik(pg) == before
