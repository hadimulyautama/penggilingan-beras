"""Owner regression for an inert pending reader, not a native editor.

Prepared for serial owner execution only. Existing native fixture recipes and
ASGI browser transport provide all actors/data. The transport blocks SW and
returns204 for EventSource: the penanda case below tests the REAL fallback
/api/keadaan→PINDAH.diam/terimaPenanda refresh protocol with one explicitly
synthetic read signal. It is not proof of a live SSE stream, PWA or Safari.
No business response DTO, permission, save, or fingerprint is fabricated.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.async_api import expect
from sqlalchemy import select

from app.models import MillingProcess
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_history_detail_owner_browser import (
    BASE, READY, SHELL, _klien, gate, native_golden, open_from_actual_row,
    peramban, two_frames,
    giling_selesai, hasil, g1, sosoh_selesai, running, dunia,
)

pytestmark = pytest.mark.asyncio
TARGET = '/barang-masuk'
DATA_TARGET = '/api/halaman-bertahap/barang-masuk'


async def menu_link(page):
    if await page.locator('#buka-laci').is_visible():
        drawer = page.locator('#laci')
        if not await drawer.is_visible():
            await page.locator('#buka-laci').click()
    link = page.locator('#laci a[href="/barang-masuk"]')
    await expect(link).to_be_visible()
    return link


async def assert_pending_has_no_editor(page):
    root = page.locator(SHELL)
    await expect(root).to_be_visible()
    assert not await root.locator('[data-editor-perintah],[data-kemas-ulang],form,[name],[data-post],[data-kirim],[data-rhs-actor]').count()
    assert await root.evaluate('r=>!r.hasAttribute("data-editor-perintah")')
    assert not await root.locator('input:not(:disabled),textarea:not(:disabled),select:not(:disabled)').count()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)


async def remember_native_identity(page, kind):
    selector = '[data-riwayat-' + kind + ']'
    native = page.locator(selector)
    await expect(native).to_be_visible()
    await expect(native).to_have_attribute('data-rhs-ready', '1')
    assert await native.evaluate('r=>r.hasAttribute("data-editor-perintah")')
    # Same key calculation as the UNCHANGED actual native design controller.
    # Keep all synthetic token/value material inside this disposable browser;
    # return booleans only, never credentials/CSRF/field values in artifacts.
    valid = await page.evaluate("""kind=>{
      const root=document.querySelector('[data-riwayat-'+kind+']'),
       memory=window[kind==='giling'?'PADI_RIWAYAT_GILING_DRAF':'PADI_RIWAYAT_SOSOH_DRAF'],
       form=root.querySelector('.riwayat-koreksi__form'),
       key=root.dataset.rhsActor+'|'+(form?.querySelector('[name=_csrf]')?.value||'');
      if(!memory||!Object.hasOwn(memory,key))return false;
      const values=Array.from(form?.elements||[]).map(node=>[node,node.value]),
       storage=Object.keys(sessionStorage).filter(k=>/koreksi|draft|draf|pending/i.test(k))
        .map(k=>[k,sessionStorage.getItem(k)]);
      window.__historyPendingOwner={root,memory,key,entry:memory[key],form,values,storage};
      return true;
    }""", kind)
    assert valid


async def assert_native_identity_preserved(page):
    valid = await page.evaluate("""()=>{
      const s=window.__historyPendingOwner;
      return !!s&&s.root.isConnected&&s.root.hasAttribute('data-editor-perintah')&&
       s.memory[s.key]===s.entry&&(!s.form||s.form.isConnected)&&
       s.values.every(([node,value])=>node.isConnected&&node.value===value)&&
       s.storage.every(([key,value])=>sessionStorage.getItem(key)===value)&&
       Object.keys(sessionStorage).filter(k=>/koreksi|draft|draf|pending/i.test(k)).length===s.storage.length;
    }""")
    assert valid


async def native_editor_veto_control(page, transport):
    """After data, existing REAL editor marker still forces native document.

    A full document waiting for HTML is intentional here. This negative
    control must not be marketed as all-pages first-click readiness.
    """
    entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    transport['gates'][TARGET] = (entered, release)
    transport['gate_headers'][TARGET] = {}
    transport['completed'][TARGET] = completed
    try:
        link = await menu_link(page)
        await link.press('Enter', no_wait_after=True)
        await asyncio.wait_for(entered.wait(), 20)
        assert await page.locator('[data-riwayat-giling][data-editor-perintah],[data-riwayat-sosoh][data-editor-perintah]').count() == 1
        assert await page.locator('[data-bm-page]').count() == 0
        await assert_native_identity_preserved(page)
    finally:
        release.set()
    await asyncio.wait_for(completed.wait(), 20)
    await page.wait_for_function("()=>location.pathname==='/barang-masuk'")
    await expect(page.locator('[data-bm-page]')).to_be_visible()


async def consume_native_penanda(page):
    """Use a DOM event from native tandaiSegar as an actual consume barrier.

    No fixed sleep and no private terimaPenanda override. The observer only
    records native DOM activity; it does not alter controller/read responses.
    """
    await page.evaluate("""()=>new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{observer.disconnect();reject(Error('native penanda consume timeout'));},10000);
      const hit=node=>node?.nodeType===1&&(node.id==='segar'||node.closest?.('#segar'));
      const observer=new MutationObserver(records=>{
        if(records.some(r=>hit(r.target)||Array.from(r.addedNodes||[]).some(hit))){
          observer.disconnect();clearTimeout(timeout);resolve(true);
        }
      });
      observer.observe(document.body,{subtree:true,childList:true,characterData:true});
      PINDAH.diam();
    })""")


async def exercise(pg, client, item, width, monkeypatch, mode):
    client.base_url = BASE
    golden = await native_golden(client, item['path'])
    assert 'data-editor-perintah' in golden
    trace = []
    signal = {'changed': False, 'reads': 0}
    original = client.request

    async def request(method, url, **kwargs):
        response = await original(method, url, **kwargs)
        path = urlsplit(str(url)).path
        headers = {k.lower(): v for k, v in kwargs.get('headers', {}).items()}
        trace.append((method.upper(), path, headers.get('x-pindah'), headers.get('x-kerangka-halaman')))
        if method.upper() == 'GET' and path == '/api/keadaan':
            assert response.status_code == 200
            data = response.json()
            assert data.get('n') and data.get('versi')
            signal['reads'] += 1
            if signal['changed']:
                # Protocol-only synthetic invalidation, not a business DTO,
                # fake tenant or DB mutation. Keep actual release/version.
                data['n'] = str(data['n']) + '.owner-pending-read-signal'
                return httpx.Response(200, json=data, headers={'Cache-Control': 'no-store'}, request=response.request)
        return response

    monkeypatch.setattr(client, 'request', request)
    before = await _sidik(pg)
    releases = []
    async with peramban(client, width) as (page, transport):
        try:
            old_release, old_completed = await open_from_actual_row(page, transport, client, item)
            releases.append(old_release)
            await assert_pending_has_no_editor(page)
            if mode == 'navigate':
                # Hold optional target HTML IF requested and its actual data
                # independently. A valid first-click frame needs neither HTML
                # nor data to finish. No invented HTML request is required.
                html_entered, html_release = asyncio.Event(), asyncio.Event()
                data_entered, data_release = asyncio.Event(), asyncio.Event()
                releases.extend([html_release, data_release])
                transport['gates'][TARGET] = (html_entered, html_release)
                transport['gate_headers'][TARGET] = {}
                transport['gates'][DATA_TARGET] = (data_entered, data_release)
                count_html = transport['gets'].count(TARGET)
                link = await menu_link(page)
                await link.press('Enter', no_wait_after=True)
                await asyncio.wait_for(data_entered.wait(), 20)
                await expect(page.locator('[data-bm-page]')).to_be_visible()
                await expect(page.locator('[data-bm-results] th')).to_have_count(6)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await expect(page.locator(SHELL)).to_have_count(0)
                assert not html_entered.is_set()
                assert transport['gets'].count(TARGET) == count_html
                old_release.set()
                await asyncio.wait_for(old_completed.wait(), 20)
                await two_frames(page)
                await expect(page.locator('[data-bm-page]')).to_be_visible()
                await expect(page.locator(SHELL + ',' + READY)).to_have_count(0)
                data_release.set()
                html_release.set()
                # The HTML barrier wasn't used; don't allow it to affect a
                # later intentional native-editor negative control.
                transport['gates'].pop(TARGET, None)
                await expect(page.locator('[data-bm-read-status]')).not_to_contain_text('Memuat daftar penerimaan')
                # Reopen with real source link, then allow actual native data.
                release, completed = await open_from_actual_row(page, transport, client, item)
                releases.append(release)
                release.set()
                await asyncio.wait_for(completed.wait(), 20)
                await expect(page.locator(READY)).to_be_visible()
                await remember_native_identity(page, item['kind'])
            else:
                assert mode == 'penanda-refresh'
                # Establish native baseline AFTER pending frame installed,
                # because native pasang() resets its private penanda to null.
                await consume_native_penanda(page)
                assert signal['reads'] >= 1
                refresh_entered, refresh_release, refresh_completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                releases.append(refresh_release)
                transport['gates'][item['path']] = (refresh_entered, refresh_release)
                transport['gate_headers'][item['path']] = {'x-pindah': '1'}
                transport['completed'][item['path']] = refresh_completed
                signal['changed'] = True
                await consume_native_penanda(page)
                await asyncio.wait_for(refresh_entered.wait(), 20)
                await assert_pending_has_no_editor(page)
                refresh_release.set()
                await asyncio.wait_for(refresh_completed.wait(), 20)
                await remember_native_identity(page, item['kind'])
                # The refresh returned a complete legitimate native editor.
                # Its identity/keys must survive the earlier pending response.
                transport['completed'][item['path']] = old_completed
                old_release.set()
                await asyncio.wait_for(old_completed.wait(), 20)
                await two_frames(page)
                await expect(page.locator(SHELL)).to_have_count(0)
                await assert_native_identity_preserved(page)
                assert signal['reads'] >= 2
                assert any(path == item['path'] and x == '1' and flag is None for _, path, x, flag in trace)
            await native_editor_veto_control(page, transport)
            assert not transport['posts'] and not transport['errors'], transport
            assert all(method == 'GET' for method, *_ in trace)
        finally:
            for release in releases:
                release.set()
    assert await _sidik(pg) == before


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
@pytest.mark.parametrize('mode', ['navigate', 'penanda-refresh'])
async def test_giling_pending_reader_can_leave_but_real_editor_keeps_its_boundary(pg, giling_selesai, width, role, mode, monkeypatch):
    _, process = giling_selesai
    async with pg() as db:
        stored = await db.scalar(select(MillingProcess).where(MillingProcess.id == process.id))
        item = dict(name='giling-' + role, kind='giling', path='/riwayat-giling/' + str(stored.id),
                    code=stored.kode_proses, source='/riwayat-giling', family='history')
    async with await _klien(pg, peran=role, gudang='Gudang 1') as client:
        await exercise(pg, client, item, width, monkeypatch, mode)


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
@pytest.mark.parametrize('mode', ['navigate', 'penanda-refresh'])
async def test_sosoh_pending_reader_can_leave_but_real_editor_keeps_its_boundary(pg, sosoh_selesai, width, role, mode, monkeypatch):
    item = dict(name='sosoh-' + role, kind='sosoh', path='/riwayat-sosoh/' + str(sosoh_selesai['id']),
                code=sosoh_selesai['kode'], source='/riwayat-sosoh', family='history')
    async with await _klien(pg, peran=role, gudang='Gudang 2') as client:
        await exercise(pg, client, item, width, monkeypatch, mode)
