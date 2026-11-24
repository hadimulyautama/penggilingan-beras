"""Detail: kerangka tanpa aksi, pembaca native segar dan tab selama GET."""
import asyncio
import json
import os

import pytest
from bs4 import BeautifulSoup
from fastapi import HTTPException
from playwright.async_api import expect

from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,warehouse,kind', [
    ('operator', 'g1', 'GABAH_KERING'), ('operator', 'g2', 'BERAS_PK'), ('admin', None, 'GABAH_KERING')])
async def test_detail_gate_shell_dan_data_native(pg, lengkap, monkeypatch, role, warehouse, kind):
    from app.web import layar_pekerjaan as layar
    tid = lengkap['tiket'][kind]
    path = '/barang-masuk/' + str(tid)
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before = await _sidik(pg)
        async def dilarang(*args, **kwargs):
            pytest.fail('Kerangka menunggu konteks/tindakan penerimaan lengkap')
        with monkeypatch.context() as m:
            m.setattr(layar, 'konteks_barang_masuk', dilarang)
            shell = await c.get(path, headers={'X-Kerangka-Halaman': '1'})
        assert shell.status_code == 200
        doc = BeautifulSoup(shell.text, 'html.parser')
        root = doc.select_one('[data-halaman-bertahap]')
        assert root and len(root.select('[role=tab]')) == 4
        assert len(root.select('table')) == 1 and len(root.select('dl')) == 3
        assert not root.select('form,input,select,textarea,[data-editor-perintah]')
        assert all(b.has_attr('disabled') or b.find_parent('fieldset',disabled=True) for b in root.select('fieldset button'))
        assert not root.select('[data-status-baca],[data-kgp-buka]')
        data = await c.get('/api/halaman-bertahap/barang-masuk-detail/' + str(tid))
        native = await c.get(path, headers={'X-Pindah':'1'})
        assert native.status_code == data.status_code == 200
        payload = data.json()
        assert payload['stamp'] == root['data-stamp']
        expected = BeautifulSoup(native.text, 'html.parser').select_one('[data-bm-detail-shell]')
        actual = BeautifulSoup(payload['html'], 'html.parser').select_one('[data-bm-detail-shell]')
        assert str(actual) == str(expected)
        assert data.headers['cache-control'] == 'private, no-store'
        if warehouse:
            denied = lengkap['tiket']['BERAS_PK' if warehouse == 'g1' else 'GABAH_KERING']
            for route in ('/barang-masuk/', '/api/halaman-bertahap/barang-masuk-detail/'):
                assert (await c.get(route + str(denied), headers={'X-Kerangka-Halaman':'1'})).status_code == 403
        assert await _sidik(pg) == before


async def test_optional_descriptor_failure_keeps_existing_four_frames(pg, lengkap, monkeypatch):
    from app.web import barang_masuk_detail_bertahap as detail
    async with await _klien(pg, role='admin') as c:
        before = await _sidik(pg)
        good = await c.get('/barang-masuk')
        catalog = BeautifulSoup(good.text, 'html.parser').select_one('[data-bm-detail-catalog]')
        assert catalog
        shape = json.loads(catalog.string)
        assert shape['targets'] and len(shape['targets']) <= 25
        assert not any('/' + str(lengkap['tiket'][k]) + '?' in t['alamat']
                       for t in shape['targets'] for k in ('BERAS_MASUK', 'BROKEN_MASUK'))
        async def unavailable(*args, **kwargs):
            raise HTTPException(404, 'Synthetic optional frame unavailable')
        monkeypatch.setattr(detail, 'kerangka', unavailable)
        response = await c.get('/barang-masuk')
        doc = BeautifulSoup(response.text, 'html.parser')
        assert response.status_code == 200 and not doc.select_one('[data-bm-detail-catalog]')
        registry = json.loads(doc.select_one('#padi-kerangka-langsung').string)
        from app.web.kerangka_langsung import LITERAL
        assert set(registry['frames']) == set(LITERAL)
        c.cookies.clear()
        assert (await c.get('/barang-masuk')).status_code == 303
        assert await _sidik(pg) == before


@pytest.mark.parametrize('role,warehouse,kind', [('operator','g1','GABAH_KERING'), ('operator','g2','BERAS_PK'), ('admin',None,'GABAH_KERING')])
@pytest.mark.parametrize('width', [390,1280])
async def test_native_click_four_tabs_delayed_error_retry_back_and_leave(pg, lengkap, monkeypatch, role, warehouse, kind, width):
    from app.web import barang_masuk_detail_bertahap as detail
    reader = detail.isi
    predicate=detail.memakai
    negotiations=[]
    def negotiated(request):
        answer=predicate(request)
        negotiations.append(dict(path=request.url.path,mode=request.headers.get('sec-fetch-mode'),dest=request.headers.get('sec-fetch-dest'),pindah=request.headers.get('x-pindah'),explicit=request.headers.get('x-kerangka-halaman'),answer=answer))
        return answer
    monkeypatch.setattr(detail,'memakai',negotiated)
    fail = {'next':False}
    async def sometimes(*args, **kwargs):
        if fail['next']:
            fail['next']=False
            raise HTTPException(503, 'Synthetic reader unavailable')
        return await reader(*args, **kwargs)
    monkeypatch.setattr(detail, 'isi', sometimes)
    tid=lengkap['tiket'][kind]; path='/barang-masuk/'+str(tid)
    api='/api/halaman-bertahap/barang-masuk-detail/'+str(tid)
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before=await _sidik(pg)
        async with peramban(c,width) as (page,transport):
            await page.goto(BASE+'/barang-masuk')
            await expect(page.locator('[data-bm-page]:not([data-bm-shell])')).to_be_visible()
            link=page.locator('a[href^="'+path+'?"]')
            await expect(link).to_have_count(1)
            parent=link.locator('xpath=ancestor::details[1]')
            if await parent.count() and not await parent.get_attribute('open') is not None:
                await parent.locator(':scope > summary').click()
            target=await link.get_attribute('href')
            entered,release=asyncio.Event(),asyncio.Event()
            transport['gates'][api]=(entered,release)
            # Candidate descriptor bypasses foreground HTML, native GET data
            # is held after server validation. No fabricated receipt/context.
            first=len(transport['gets'])
            await link.click()
            await asyncio.wait_for(entered.wait(),30)
            shell=page.locator('[data-halaman-bertahap][data-kind=barang-masuk-detail]')
            await expect(shell).to_be_visible()
            assert path not in transport['gets'][first:]
            assert await page.locator('[data-bm-back]').get_attribute('href')=='/barang-masuk'
            await expect(shell.locator('[role=tab]')).to_have_count(4)
            for key in ('tiket','qc','riwayat','ringkasan'):
                tab=shell.locator('[data-bm-tab='+key+']')
                await tab.focus();await tab.press('Enter')
                await expect(shell.locator('[data-bm-detail-panel='+key+']' )).to_be_visible()
                await expect(tab).to_be_focused()
            await shell.locator('[data-bm-tab=qc]').click()
            release.set()
            try:
                await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
            except AssertionError:
                print('DETAIL_READ_DIAGNOSTIC', await page.locator('[data-shell-status]').all_text_contents(), transport['errors'])
                raise
            await expect(page.locator('[data-bm-detail-panel=qc]')).to_be_visible()
            # Native full data is installed with the tab chosen while waiting.
            await expect(page.locator('[data-bm-tab=qc]')).to_be_focused()
            assert 'tab_detail=qc' in page.url
            await expect(page.locator('.bar__merek')).to_contain_text('Penerimaan TRX-391-')
            assert 'Penerimaan TRX-391-' in await page.title()
            # The in-process route adapter does not expose browser-generated
            # Sec-Fetch headers. Exercise the explicit renderer negotiation
            # here; genuine document headers are covered by native HTTP.
            await page.set_extra_http_headers({'X-Kerangka-Halaman':'1'})
            await page.reload()
            await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
            await expect(page.locator('[data-bm-detail-panel=qc]')).to_be_visible()
            fail['next']=True
            await page.goto(BASE+target)
            try:
                await expect(page.locator('[data-shell-retry]')).to_be_visible()
            except AssertionError:
                print('DETAIL_ERROR_NEGOTIATION',negotiations,transport['gets'],fail)
                raise
            await expect(page.locator('[data-shell-message]')).to_contain_text('bukan daftar kosong')
            await page.locator('[data-shell-retry]').click()
            await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
            # Hold another read, leave before release, and prove no stale swap.
            entered,release=asyncio.Event(),asyncio.Event()
            transport['gates'][api]=(entered,release)
            await page.goto(BASE+target)
            await asyncio.wait_for(entered.wait(),30)
            back=page.locator('[data-bm-back]')
            await back.click()
            await expect(page.locator('[data-bm-page]')).to_be_visible()
            release.set()
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            await expect(page.locator('[data-bm-detail-shell]')).to_have_count(0)
            assert not transport['posts'] and not transport['errors']
        assert await _sidik(pg)==before
