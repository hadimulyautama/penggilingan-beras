"""PREPARED owner Users acceptance, outside product checkout until adopted.

Not executed. Existing native helpers/role types only. All setup completes
before fingerprints; browser thereafter GET-only. No create/reset/status/save
button is clicked, no POST secret-response is fetched, no credential/cookie or
raw HTML is persisted. Native peramban uses ASGI with service_workers=block,
not a real PWA/network/hosted proof. Explicit document protocol is separate.
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

from hmu_identitas import peran as P
from tests.pg.test_kelola_akun_http import _super, _token, _klien
from tests.pg.test_pengaturan_usulan import master, klien
from tests.pg.test_portal_pelanggan import portal
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_barang_masuk_bertahap_browser import BASE, peramban
from tests.pg.test_halaman_bertahap import _sidik

pytestmark = pytest.mark.asyncio
NATIVE = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
DOCUMENT = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
SHELL = '[data-pengguna-baca-native]'
READY = '[data-pengguna-baca-native-isi]'
SETTINGS_SHELL = '[data-pengaturan-menu-kerangka]'


def address(value):
    parsed = urlsplit(value)
    assert not parsed.netloc or parsed.netloc == 'uji'
    return parsed.path + ('?' + parsed.query if parsed.query else '')


def chrome(html):
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    assert main is not None
    bar = main.select_one('header.bar')
    brand = bar.select_one('.bar__merek')
    control = bar.select_one('.bar__menu,.bar__balik')
    assert brand is not None and control is not None
    crumb = main.select_one('.desktop-chrome__crumbrow')
    trail = []
    for li in crumb.select('nav.desktop-breadcrumb ol > li'):
        item = li.select_one('a[href],[aria-current=page]')
        assert item is not None
        trail.append(dict(tag=item.name, text=item.get_text(' ', strip=True),
                          href=item.get('href'), current=item.get('aria-current')))
    back = crumb.select_one('a.desktop-back')
    assert back is not None
    return dict(title=doc.title.get_text(), brand=brand.get_text(' ', strip=True),
                brand_label=brand.get('aria-label'),
                control=dict(tag=control.name, classes=control.get('class'),
                             href=control.get('href'), label=control.get('aria-label'),
                             id=control.get('id')),
                trail=trail, back=dict(href=back.get('href'), label=back.get('aria-label')),
                h1=[n.get_text(' ', strip=True) for n in main.select('h1')],
                h2=[n.get_text(' ', strip=True) for n in main.select('h2')],
                tables=[[n.get_text(' ', strip=True) for n in head.select('th')]
                        for head in main.select('thead')])


def fields(html):
    """Native labels/types, not values, roles, passwords or CSRF tokens."""
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    result = []
    for label in main.select('label'):
        target = doc.find(id=label.get('for')) if label.get('for') else label.select_one('input,select,textarea')
        if target is None:
            continue
        # A label may wrap help/field children. Its own text names the field;
        # help text is not a second input and selected role is never inferred.
        own = ' '.join(str(n).strip() for n in label.find_all(string=True, recursive=False) if str(n).strip())
        if not own:
            own = label.get_text(' ', strip=True)
        result.append((own, target.name, target.get('type', 'text') if target.name == 'input' else None))
    return result


def no_secret_response(response):
    if not response.headers.get('content-type','').startswith('text/html'):return
    doc=BeautifulSoup(response.text,'html.parser')
    count=len(doc.select('.sandi-awal'))
    if count:
        # Do not let assertion introspection render the secret-bearing Tag.
        doc=None
        raise AssertionError('Unexpected secret reveal on GET; body/artifact suppressed') from None


async def golden(client, target):
    response = await client.get(target, headers=NATIVE)
    assert response.status_code == 200, (target, response.status_code)
    no_secret_response(response)
    doc = BeautifulSoup(response.text, 'html.parser')
    assert len(doc.select(SHELL))==0
    return response.text


async def targets(client):
    staff = BeautifulSoup(await golden(client, '/pengguna'), 'html.parser')
    staff_links = staff.select('.daftar-standar > .daftar-standar__baris a[href]')
    staff_links = [link for link in staff_links if link.get('href', '').removeprefix('/pengguna/').isdecimal()]
    assert staff_links, 'Existing native Super fixture must appear as an actual staff row'
    customers = BeautifulSoup(await golden(client, '/pengguna/pelanggan'), 'html.parser')
    customer_links = [link for link in customers.select('.kelola-portal table tbody tr a[href]')
                      if link.get('href', '').startswith('/pengguna/pelanggan/')]
    assert customer_links, 'Existing portal fixture must supply a real native account row'
    # This selected recipe includes qc's existing person without a login.
    # Do not silently relax the field oracle to hide a changed recipe.
    assert staff.select_one('form[action="/pengguna/buat"]'), 'Selected native recipe no longer has the ordinary people-choice form'
    return address(staff_links[0]['href']), address(customer_links[0]['href'])


class Barrier:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()


class ReadPhases:
    """Two real transport phases, after native auth/read, without success mocks."""
    def __init__(self, client, monkeypatch):
        self.path = None
        self.html = self.data = None
        self.fault = None
        self.trace = []
        self.original = client.request
        monkeypatch.setattr(client, 'request', self.request)

    def arm(self, target, fault=None):
        self.path = address(target)
        self.html, self.data = Barrier(), Barrier()
        self.fault = fault
        return self.html, self.data

    def free(self):
        if self.html:
            self.html.release.set()
        if self.data:
            self.data.release.set()
        self.path = None

    async def request(self, method, url, **kwargs):
        target = address(str(url))
        headers = {key.lower(): value for key, value in kwargs.get('headers', {}).items()}
        response = await self.original(method, url, **kwargs)
        if method.upper()=='GET':no_secret_response(response)
        kind = 'data' if headers.get('x-pindah') == '1' and headers.get('x-kerangka-halaman') == '0' else 'html'
        self.trace.append(dict(method=method.upper(), address=target, phase=kind,
                               document=headers.get('sec-fetch-dest') == 'document'))
        if method.upper() != 'GET' or target != self.path:
            return response
        barrier = self.data if kind == 'data' else self.html
        fault = self.fault if kind == 'data' else None
        if fault:
            assert response.status_code == 200, 'Fault must follow a real authorised native 200'
            self.fault = None
            if fault == '503':
                response = httpx.Response(503, text='Owner fixture read unavailable',
                    headers={'content-type': 'text/html'}, request=response.request)
            else:
                assert fault == 'context'
                import re
                body, count = re.subn(r'data-pindah-konteks="[^"]+"',
                                      'data-pindah-konteks="owner-stale-context"', response.text, count=1)
                assert count == 1
                response = httpx.Response(200, text=body,
                    headers={'content-type': 'text/html'}, request=response.request)
        barrier.entered.set()
        try:
            await barrier.release.wait()
            return response
        finally:
            barrier.finished.set()


def save_trace_safe(phases,folder):
    if folder is None:return
    folder.mkdir(parents=True,exist_ok=True)
    payload={'requests':phases.trace,'last_phase':dict(target=phases.path,
        html_entered=bool(phases.html and phases.html.entered.is_set()),
        data_entered=bool(phases.data and phases.data.entered.is_set()),
        data_finished=bool(phases.data and phases.data.finished.is_set()))}
    (folder/'navigation-phases.json').write_text(json.dumps(payload,indent=2))


async def two_frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def screenshot_safe(page, folder, name):
    # Do not save a secret reveal even if a GET/renderer regression occurs.
    assert await page.locator('.sandi-awal').count()==0, 'Secret-reveal artefact suppressed'
    assert await page.locator('input[type=password]').evaluate_all('nodes=>nodes.every(n=>n.value==="")'), 'Nonempty password artefact suppressed'
    await page.screenshot(path=str(folder/name),full_page=True)


async def compare(page, expected_html):
    assert chrome(await page.content()) == chrome(expected_html)
    assert fields(await page.content()) == fields(expected_html)


async def no_mutation_ui(page, transport):
    assert not transport['posts'], 'Owner navigation must never issue a POST'
    assert not transport['errors'], transport['errors']
    assert await page.locator('.sandi-awal').count() == 0


async def open_held(page, phases, target, link, expected, shell=SHELL):
    if shell==SHELL:
        # Read-only diagnostic of the actual current bindings. No token,
        # name, HTML, role grant or fabricated success DTO is returned.
        probe=await page.evaluate('''target=>{
          const frame=document.querySelector('.bingkai'),cap=document.documentElement.dataset.versi,
            token=document.getElementById('formulir-sesi')?.dataset.token,
            registry=document.getElementById('padi-kerangka-langsung'),host=document.getElementById('padi-pengguna-kerangka');
          const result={registry:!!registry,host:!!host,program:!!window.PadiKerangkaPenggunaUI,
            marked:!!document.querySelector('[data-editor-perintah],[data-kemas-ulang]'),
            frameAddress:frame?.dataset.pindahAlamat===location.pathname+location.search};
          try{
            const p=host?JSON.parse(host.textContent):null,d=window.PadiKerangkaPenggunaData;
            result.permissionBound=!!p&&p.cap===cap&&p.konteks===frame?.dataset.pindahKonteks&&p.sesi===token&&p.sumber===d?.sumber;
            const r=registry?JSON.parse(registry.textContent):null,base=r?.frames?.['/barang-masuk']?.map(i=>r.potongan[i]).join('');
            result.registryBound=!!r&&r.cap===cap&&r.konteks===frame?.dataset.pindahKonteks&&r.sesi===token;
            result.factory=!!window.PadiKerangkaPenggunaUI?.buat(target,base,frame?.dataset.pindahKonteks,cap,token);
          }catch(e){result.errorType=e.name;}
          return result;
        }''',target)
        assert probe.get('factory'),probe
        await expect(link).to_be_visible()
    html, data = phases.arm(target)
    await link.press('Enter')
    # A fallback HTML-first request would remain held and this assertion must
    # fail. Do not change the barrier headers just to make a fallback pass.
    await asyncio.wait_for(data.entered.wait(), 20)
    root = page.locator(shell)
    await expect(root).to_be_visible()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    await compare(page, expected)
    assert not html.entered.is_set(), 'First-click must not wait for target HTML'
    # Release the HTML phase independently: the actual data is STILL held.
    html.release.set()
    await two_frames(page)
    await expect(root).to_be_visible()
    await compare(page, expected)
    if shell == SHELL:
        assert await root.locator('form,[name],input[type=hidden]').count() == 0
        assert await root.locator('input:not(:disabled),select:not(:disabled),textarea:not(:disabled)').count() == 0
        assert await root.locator('button:not(:disabled):not([data-pengguna-baca-retry])').count() == 0
    return root, data


async def release_data(page, phases, root, barrier, expected, ready=READY):
    barrier.release.set()
    await asyncio.wait_for(barrier.finished.wait(), 20)
    await expect(root).to_have_count(0, timeout=20000)
    await expect(page.locator(ready)).to_be_visible()
    await compare(page, expected)
    phases.free()


async def source_users(page, kind):
    path = '/pengguna' if kind == 'staff' else '/pengguna/pelanggan'
    await page.goto(BASE + path, wait_until='load')
    await expect(page.locator(READY)).to_be_visible()
    await page.wait_for_function("""path=>{
      const host=document.getElementById('padi-pengguna-kerangka'),frame=document.querySelector('.bingkai');
      const catalog=document.querySelector('[data-pengguna-native-catalog]');
      return window.PadiKerangkaPenggunaUI&&host&&catalog&&frame&&
        frame.dataset.pindahAlamat===path&&catalog.dataset.sourceAddress===path;
    }""", arg=path)


@pytest.mark.parametrize('width', [390, 1280], ids=['super-390', 'super-desktop'])
async def test_sidebar_settings_staff_customer_actual_detail_and_back(pg, portal, monkeypatch, width):
    sid = await _super(pg, username='users-owner-super')
    async with _klien(await _token(pg, sid)) as client:
        client.base_url = BASE
        staff_target, customer_target = await targets(client)
        native = {path: await golden(client, path) for path in
                  ('/pengaturan', '/pengguna', staff_target, '/pengguna/pelanggan', customer_target)}
        before = await _sidik(pg)
        phases = ReadPhases(client, monkeypatch)
        folder = Path(os.environ['DETAIL_OUT']) / ('users-' + str(width)) if os.environ.get('DETAIL_OUT') else None
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
        async with peramban(client, width) as (page, transport):
            try:
                await page.goto(BASE + '/barang-masuk', wait_until='load')
                await page.wait_for_function("()=>window.PadiKerangkaPengaturanUI&&document.getElementById('padi-pengaturan-kerangka')")
                if width < 900:
                    await page.locator('#buka-laci').click()
                settings_link = page.locator('#laci a[href="/pengaturan"]')
                root, data = await open_held(page, phases, '/pengaturan', settings_link, native['/pengaturan'], SETTINGS_SHELL)
                await release_data(page, phases, root, data, native['/pengaturan'], '[data-pengaturan-menu-isi]')
                # This is the crucial new metadata adoption hop, not direct URL setup.
                await expect(page.locator('#padi-pengguna-kerangka')).to_have_count(1)
                root, data = await open_held(page, phases, '/pengguna', page.locator('.pg-pintu[href="/pengguna"]'), native['/pengguna'])
                await release_data(page, phases, root, data, native['/pengguna'])
                await expect(page.locator('[data-pengguna-native-catalog]')).to_have_count(1)
                staff_link = page.locator('.daftar-standar__baris a[href="' + staff_target + '"]')
                await expect(staff_link).to_have_count(1)
                root, data = await open_held(page, phases, staff_target, staff_link, native[staff_target])
                if folder:
                    await screenshot_safe(page,folder,'staff-detail-before.png')
                await release_data(page, phases, root, data, native[staff_target])
                await expect(page.locator('input[name=nama]')).to_be_enabled()
                if folder:
                    await screenshot_safe(page,folder,'staff-detail-after.png')
                root, data = await open_held(page, phases, '/pengguna', page.get_by_role('link', name='Kembali ke daftar', exact=True), native['/pengguna'])
                await release_data(page, phases, root, data, native['/pengguna'])
                customer_link = page.locator('nav[aria-label="Jenis pengguna"] a[href="/pengguna/pelanggan"]')
                root, data = await open_held(page, phases, '/pengguna/pelanggan', customer_link, native['/pengguna/pelanggan'])
                await release_data(page, phases, root, data, native['/pengguna/pelanggan'])
                account_link = page.locator('.kelola-portal table a[href="' + customer_target + '"]')
                await expect(account_link).to_have_count(1)
                root, data = await open_held(page, phases, customer_target, account_link, native[customer_target])
                if folder:
                    await screenshot_safe(page,folder,'customer-detail-before.png')
                await release_data(page, phases, root, data, native[customer_target])
                assert await page.locator('input[type=password]').count() == 2
                assert await page.locator('input[type=password]').evaluate_all('nodes=>nodes.every(n=>n.value==="")')
                root, data = await open_held(page, phases, '/pengguna/pelanggan', page.get_by_role('link', name='Kembali ke daftar', exact=True), native['/pengguna/pelanggan'])
                await release_data(page, phases, root, data, native['/pengguna/pelanggan'])
                await page.go_back(wait_until='load')
                await page.wait_for_function('path=>location.pathname===path', arg=customer_target)
                await expect(page.locator(READY)).to_be_visible()
                await compare(page, native[customer_target])
                await no_mutation_ui(page, transport)
            finally:
                # Save only safe phase diagnostics, including when a held
                # HTML fallback prevents the data barrier from being entered.
                save_trace_safe(phases,folder)
                phases.free()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280], ids=['read-errors-390', 'read-errors-desktop'])
async def test_users_retry_stale_abandon_and_does_not_steal_later_header_focus(pg, portal, monkeypatch, width):
    sid = await _super(pg, username='users-retry-super')
    async with _klien(await _token(pg, sid)) as client:
        client.base_url = BASE
        staff_target, _ = await targets(client)
        expected = await golden(client, staff_target)
        before = await _sidik(pg)
        phases = ReadPhases(client, monkeypatch)
        async with peramban(client, width) as (page, transport):
            try:
                for fault in ('503', 'context'):
                    await source_users(page, 'staff')
                    html, data = phases.arm(staff_target, fault=fault)
                    await page.locator('.daftar-standar__baris a[href="' + staff_target + '"]').press('Enter')
                    await asyncio.wait_for(data.entered.wait(), 20)
                    root = page.locator(SHELL)
                    await expect(root).to_be_visible()
                    data.release.set()
                    await asyncio.wait_for(data.finished.wait(), 20)
                    retry = root.locator('[data-pengguna-baca-retry]')
                    await expect(retry).to_be_visible()
                    await expect(root.locator('[data-pengguna-baca-status]')).to_have_attribute('role', 'alert')
                    await compare(page, expected)
                    phases.free()
                    html, data = phases.arm(staff_target)
                    await retry.focus()
                    await page.keyboard.press('Enter')
                    await asyncio.wait_for(data.entered.wait(), 20)
                    # A subsequent native header focus belongs to the user.
                    # It survives the content swap and must not be pulled back
                    # to Retry/container. No system Tab preference is changed.
                    back = page.locator('header.bar a.bar__balik')
                    await back.focus()
                    await page.keyboard.press('ArrowRight')
                    await expect(back).to_be_focused()
                    data.release.set()
                    await expect(root).to_have_count(0, timeout=20000)
                    await expect(back).to_be_focused()
                    await compare(page, expected)
                    phases.free()
                await source_users(page, 'staff')
                html, data = phases.arm(staff_target)
                await page.locator('.daftar-standar__baris a[href="' + staff_target + '"]').press('Enter')
                await asyncio.wait_for(data.entered.wait(), 20)
                await expect(page.locator(SHELL)).to_be_visible()
                await page.locator('header.bar a.bar__balik').press('Enter')
                await page.wait_for_function('()=>location.pathname==="/pengguna"')
                await expect(page.locator(READY)).to_be_visible()
                data.release.set()
                await asyncio.wait_for(data.finished.wait(), 20)
                await two_frames(page)
                assert await page.locator('[data-pengguna-variant="staf-detail"]').count() == 0
                assert await page.locator('form[action="' + staff_target + '"]').count() == 0
                await no_mutation_ui(page, transport)
            finally:
                phases.free()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('role,warehouse,width', [(P.ADMIN, None,1280), (P.OPERATOR, 'Gudang 1',390)], ids=['ordinary-admin', 'operator-g1'])
async def test_native_user_doors_denied_with_active_super_not_legacy_fallback(pg, master, portal, role, warehouse,width):
    from app.web import security
    sid = await _super(pg, username='users-denial-super')
    assert await security.ada_superadmin()
    assert not await security.pemulihan_lama_diizinkan()
    async with _klien(await _token(pg,sid)) as source:
        source.base_url=BASE
        staff_target,customer_target=await targets(source)
    client, _, _ = await klien(pg, role, warehouse, username='users-denied', nama='Pemeriksa Ditolak')
    async with client:
        client.base_url = BASE
        before = await _sidik(pg)
        for target in ('/pengguna',staff_target,'/pengguna/pelanggan',customer_target):
            native = await client.get(target, headers=NATIVE)
            document = await client.get(target, headers=DOCUMENT)
            assert native.status_code == document.status_code == 403
            assert not BeautifulSoup(document.text, 'html.parser').select(SHELL + ',#padi-pengguna-kerangka,[data-pengguna-native-catalog]')
        settings = await client.get('/pengaturan', headers=NATIVE)
        assert settings.status_code == 200
        assert not BeautifulSoup(settings.text, 'html.parser').select('.pg-pintu[href="/pengguna"]')
        async with peramban(client,width) as (page,transport):
            await page.goto(BASE+'/barang-masuk',wait_until='load')
            if width<900:
                await page.locator('#buka-laci').click()
            await page.locator('#laci a[href="/pengaturan"]').press('Enter')
            await expect(page.locator('[data-pengaturan-menu-isi]')).to_be_visible()
            await expect(page.locator('.pg-pintu[href="/pengguna"]')).to_have_count(0)
            await expect(page.locator('#padi-pengguna-kerangka,[data-pengguna-native-catalog]')).to_have_count(0)
            await no_mutation_ui(page,transport)
        assert await _sidik(pg) == before


async def test_explicit_document_protocol_separate_from_headerless_asgi_and_native_data(pg, portal):
    sid = await _super(pg, username='users-protocol-super')
    async with _klien(await _token(pg, sid)) as client:
        client.base_url = BASE
        staff_target, customer_target = await targets(client)
        before = await _sidik(pg)
        for target in ('/pengguna', staff_target, '/pengguna/pelanggan', customer_target):
            # Direct httpx has no browser Sec-Fetch by default. Do not turn a
            # headerless legacy GET into a document-shell assertion.
            headerless = await client.get(target)
            no_secret_response(headerless)
            native = await client.get(target, headers=NATIVE)
            document = await client.get(target, headers=DOCUMENT)
            no_secret_response(native);no_secret_response(document)
            assert headerless.status_code == native.status_code == document.status_code == 200
            assert not BeautifulSoup(headerless.text, 'html.parser').select(SHELL)
            assert not BeautifulSoup(native.text, 'html.parser').select(SHELL)
            pending = BeautifulSoup(document.text, 'html.parser').select_one(SHELL)
            assert pending is not None
            assert not pending.select('form,[name],input[type=hidden]')
            assert all(node.has_attr('disabled') for node in pending.select('input,select,textarea'))
            assert chrome(document.text) == chrome(native.text)
            assert fields(document.text) == fields(native.text)
            assert 'no-store' in document.headers.get('cache-control', '')
            assert len(BeautifulSoup(document.text,'html.parser').select('.sandi-awal'))==0
        assert await _sidik(pg) == before
