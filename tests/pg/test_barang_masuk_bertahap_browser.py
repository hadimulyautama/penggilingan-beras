"""Native browser/ASGI reads; SSE is an explicit comment-only protocol scaffold.

This bridge does not prove native SSE messages, authentication, reconnects or
PWA behavior. Actual HTTP/SSE acceptance has separate owner receipts. The
scaffold contains no application DTO and never suppresses browser page errors.
"""
import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.async_api import Error as BrowserError, async_playwright, expect
from sqlalchemy.exc import SQLAlchemyError

from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark = pytest.mark.asyncio
BASE = 'https://uji'
SSE_PROTOCOL_COMMENT = ': fixture protocol scaffold; no application message\n\n'


@asynccontextmanager
async def peramban(client, width):
    """ASGI supplies native page data; the SSE branch is protocol-only, not data."""
    gates, posts, errors = {}, [], []
    transport = dict(gates=gates, gate_headers={}, pad_html={}, posts=posts, errors=errors, gets=[], completed={}, corrupt_context=False, fail_asset=False)
    transport['sse_scaffold'] = dict(status=200, mime='text/event-stream', requests=0,
        comment_only=True, application_DTO_supplied=False, native_SSE_coverage=False)
    pending = set()
    closing = False
    async with async_playwright() as pw:
        engine = os.environ.get('UJI_BROWSER', os.environ.get('OWNER_BROWSER', 'chromium'))
        assert engine in {'chromium', 'webkit'}
        browser = await getattr(pw, engine).launch()
        context = await browser.new_context(viewport={'width': width, 'height': 900},
                                            service_workers='block', reduced_motion='reduce')
        await context.add_cookies([dict(name=x.name, value=x.value, url=BASE) for x in client.cookies.jar])
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        async def route(route):
            request = route.request
            u = urlsplit(request.url)
            if closing or u.netloc != 'uji':
                await route.abort()
                return
            if u.path == '/api/aliran':
                # Native endpoint is a 200 text/event-stream. This finite idle
                # comment is only a protocol scaffold; it supplies no penanda
                # or business value. Do not infer reconnect/auth/stream health
                # from these intercepted page-navigation tests.
                transport['sse_scaffold']['requests'] += 1
                await route.fulfill(status=200, content_type='text/event-stream',
                    headers={'Cache-Control': 'no-cache'}, body=SSE_PROTOCOL_COMMENT)
                return
            if request.method != 'GET':
                posts.append(u.path)
            else:
                transport['gets'].append(u.path)
            if u.path == '/static/barang-masuk-pencarian.js' and transport['fail_asset']:
                await route.fulfill(status=503, body='Fixture asset unavailable')
                return
            headers = await request.all_headers()
            job = asyncio.create_task(client.request(request.method,
                u.path + ('?' + u.query if u.query else ''), content=request.post_data_buffer,
                headers={k: v for k, v in headers.items() if k in {
                    'content-type', 'x-csrf-token', 'x-pindah', 'x-kerangka-halaman',
                    'x-barang-masuk-cari', 'accept', 'sec-fetch-mode', 'sec-fetch-dest',
                    'sec-fetch-site', 'sec-fetch-user'}}))
            pending.add(job)
            gate = None
            try:
                response = await asyncio.wait_for(asyncio.shield(job), 60)
                required=transport['gate_headers'].get(u.path,{})
                gate = gates.pop(u.path,None) if all(headers.get(key)==value for key,value in required.items()) else None
                if gate:
                    gate[0].set()
                    await gate[1].wait()
                body = response.content
                padding=transport['pad_html'].pop(u.path,0) if headers.get('x-pindah')=='1' and headers.get('x-kerangka-halaman')=='0' else 0
                if padding:
                    assert request.method=='GET' and response.status_code==200 and response.headers.get('content-type','').startswith('text/html')
                    assert type(padding) is int and 0<padding<=16*1024*1024
                    # Owner-only negative: pad AFTER actual native auth/read,
                    # preserving its markers. No DB rows/response identity are fabricated.
                    body=body.replace(b'</body>',b'<!-- synthetic owner size padding -->'+b'x'*padding+b'</body>',1)
                if u.path == '/barang-masuk' and transport['corrupt_context']:
                    transport['corrupt_context'] = False
                    # Negative response-provenance control, not fake business
                    # data or a claim that two warehouses are two companies.
                    body = re.sub(rb'data-bm-context="[^"]+"', b'data-bm-context="stale-response"', body, count=1)
                await route.fulfill(status=response.status_code, body=body,
                    headers={k: v for k, v in response.headers.items() if k.lower() not in {
                        'content-length', 'content-encoding', 'transfer-encoding', 'set-cookie'}})
            except BrowserError:
                if not (gate or closing or request.failure):
                    raise
            finally:
                pending.discard(job)
                completed = transport['completed'].get(u.path)
                if gate and completed:
                    completed.set()
        await context.route('**/*', route)
        try:
            yield page, transport
        finally:
            closing = True
            for entered, release in list(gates.values()):
                release.set()
            if pending:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 65)
            await context.close()
            await browser.close()


@pytest.mark.parametrize('role,warehouse', [(P.OPERATOR, 'g1'), (P.OPERATOR, 'g2'), (P.ADMIN, None)])
@pytest.mark.parametrize('width', [390, 1280])
async def test_daftar_loading_filter_error_retry_stale_dan_keluar(
        pg, lengkap, monkeypatch, role, warehouse, width):
    from app.services import barang_masuk_daftar
    native_reader = barang_masuk_daftar.daftar
    fail = dict(next=False)
    async def reader(*args, **kwargs):
        if fail['next']:
            fail['next'] = False
            raise SQLAlchemyError('fixture read unavailable')
        return await native_reader(*args, **kwargs)
    monkeypatch.setattr(barang_masuk_daftar, 'daftar', reader)
    initial_entered, initial_release = asyncio.Event(), asyncio.Event()
    late_entered, late_release = asyncio.Event(), asyncio.Event()
    search_entered, search_release = asyncio.Event(), asyncio.Event()
    error_entered, error_release = asyncio.Event(), asyncio.Event()
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before = await _sidik(pg)
        async with peramban(c, width) as (page, transport):
            try:
                transport['gates']['/api/halaman-bertahap/barang-masuk'] = (initial_entered, initial_release)
                await page.goto(BASE + '/kabar')
                if width < 900:
                    await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/barang-masuk"]').click()
                await asyncio.wait_for(initial_entered.wait(), 15)
                root = page.locator('[data-bm-page]')
                await expect(root.locator('[data-bm-results] th')).to_have_count(6)
                await expect(root.locator('[data-bm-results] tbody tr')).to_have_count(1)
                assert await root.get_attribute('aria-busy') is None
                await expect(root.locator('[data-bm-results]')).to_have_attribute('aria-busy','true')
                assert transport['gets'].count('/api/halaman-bertahap/barang-masuk') == 1
                await expect(root.locator('[data-bm-state-message]')).to_contain_text('Memuat')
                await expect(root.locator('.kontrol-filter')).to_be_enabled()
                await root.locator('.kontrol-filter').click()
                await expect(root.locator('#bm-filter')).to_be_visible()
                await expect(root.locator('#bm-filter [name=pemasok]')).to_be_disabled()
                await page.keyboard.press('Escape')
                await expect(root.locator('.kontrol-filter')).to_be_focused()
                search = root.locator('[data-bm-search] input[name=cari]')
                await search.fill('Kode tidak ditemukan')
                initial_release.set()
                await expect(root.locator('[data-bm-read-status]')).to_contain_text('Isian pilihan tetap dipertahankan')
                await expect(search).to_be_focused()
                await expect(search).to_have_value('Kode tidak ditemukan')
                transport['gates']['/barang-masuk'] = (search_entered, search_release)
                await search.press('Enter')
                await asyncio.wait_for(search_entered.wait(), 15)
                await expect(search).to_be_focused()
                await search.press('Tab')
                # Default WebKit may skip buttons; preserve its actual semantic
                # destination rather than force Chromium's Tab preference.
                destination = await page.evaluate("()=>document.activeElement.matches('.bm-state-scroll')?'region':document.activeElement.matches('[data-bm-search] button[type=submit]')?'search':document.activeElement.tagName")
                assert destination in {'region', 'search'}, destination
                search_release.set()
                await expect(root.locator('[data-bm-state-message]')).to_contain_text('Tidak ada penerimaan yang cocok')
                await expect(root.locator('[data-bm-results] th')).to_have_count(6)
                target = root.locator('.bm-state-scroll' if destination == 'region' else '[data-bm-search] button[type=submit]')
                await expect(target).to_be_focused()
                await search.fill('')
                await search.press('Enter')
                await expect(root.locator('[data-bm-read-status]')).to_contain_text('Data siap')
                await search.press('Tab')
                await expect(root.locator('[data-bm-results] .antrian-item').first).to_be_visible()

                fail['next'] = True
                transport['gates']['/barang-masuk'] = (error_entered, error_release)
                await page.locator('nav[aria-label="Bagian Barang Masuk"] a[href*="status=diterima"]').click()
                await asyncio.wait_for(error_entered.wait(), 15)
                await search.focus()
                for _ in range(3):
                    await page.keyboard.press('Tab')
                    if await page.evaluate("()=>document.activeElement.matches('.bm-state-scroll')"):
                        break
                await expect(root.locator('.bm-state-scroll')).to_be_focused()
                error_release.set()
                await expect(root.locator('[data-bm-error]')).to_be_visible()
                await expect(root.locator('.bm-state-scroll')).to_be_focused()
                await expect(page.locator('nav[aria-label="Bagian Barang Masuk"] a[href*="status=diterima"]')).to_have_attribute('aria-current','page')
                await expect(root.locator('.bm-jumlah')).to_contain_text('Jumlah hasil belum tersedia')
                await expect(root.locator('[data-bm-results] th')).to_have_count(7)
                await expect(root.locator('[data-bm-state-message]')).to_contain_text('gagal dimuat')
                await expect(root.locator('.kontrol-filter')).to_be_enabled()
                await root.locator('[data-bm-retry]').click()
                await expect(root.locator('[data-bm-error]')).to_be_hidden()
                await expect(root.locator('[data-bm-read-status]')).not_to_have_text('Memuat daftar penerimaan…')

                search = root.locator('[data-bm-search] input[name=cari]')
                await search.fill('TRX-391')
                transport['corrupt_context'] = True
                await search.press('Enter')
                await expect(root.locator('[data-bm-read-status]')).to_contain_text('Sesi, gudang atau versi berubah')
                await expect(root.locator('[data-bm-error]')).to_be_visible()
                await root.locator('[data-bm-retry]').click()
                await expect(root.locator('[data-bm-error]')).to_be_hidden()

                late_done = asyncio.Event()
                transport['completed']['/barang-masuk'] = late_done
                transport['gates']['/barang-masuk'] = (late_entered, late_release)
                await search.fill('Respons ditinggalkan')
                await search.press('Enter')
                await asyncio.wait_for(late_entered.wait(), 15)
                await page.locator('a[href="/kabar"]:visible').first.click()
                await expect(page).to_have_url(BASE + '/kabar')
                late_release.set()
                await asyncio.wait_for(late_done.wait(), 15)
                await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                await expect(page.locator('[data-bm-page]')).to_have_count(0)
                assert not transport['posts']
                assert not transport['errors'], transport['errors']
            finally:
                initial_release.set()
                late_release.set()
                search_release.set()
                error_release.set()
        assert await _sidik(pg) == before


@pytest.mark.parametrize('width', [390, 1280])
async def test_reload_commit_opaque_memulihkan_key_status_tanpa_post_ulang(pg, lengkap, width):
    """One real fixture receipt commit; only its HTTP outcome is cut."""
    tid = lengkap['tiket']['GABAH_KERING']
    path = '/barang-masuk/' + str(tid)
    entered, asset_release = asyncio.Event(), asyncio.Event()
    gate_asset = dict(next=False)
    bodies = []
    async with await _klien(pg, role=P.OPERATOR, gudang_id=lengkap['gudang']['g1']) as c:
        native = c.request
        async def request(method, url, **kwargs):
            if method == 'POST':
                assert str(url) == '/api/actions/gabah-masuk'
                bodies.append(json.loads(kwargs['content']))
                assert len(bodies) == 1
                response = await native(method, url, **kwargs)
                assert response.status_code == 200
                return httpx.Response(503, json={'detail': 'Fixture opaque outcome after commit'})
            response = await native(method, url, **kwargs)
            if urlsplit(str(url)).path == '/static/penerimaan-ringkas.js' and gate_asset['next']:
                gate_asset['next'] = False
                entered.set()
                await asset_release.wait()
            return response
        c.request = request
        async with peramban(c, width) as (page, transport):
            async def reload_dialog(dialog):
                assert dialog.type == 'beforeunload'
                await dialog.accept()
            page.on('dialog', reload_dialog)
            try:
                await page.goto(BASE + path + '#terima-panel-qc')
                root = page.locator('[data-bm-detail-shell]')
                await expect(page).to_have_url(re.compile(r'.*#terima-panel-qc$'))
                await expect(root.locator('[data-bm-tab="qc"]')).to_have_attribute('aria-selected','true')
                await root.locator('[data-bm-tab="ringkasan"]').click()
                form = root.locator('[data-formulir] form')
                await expect(form).to_be_visible()
                await form.locator('[name=warehouse_id]').select_option(str(lengkap['gudang']['g1']))
                await form.locator('[name=tujuan]').select_option('tumpuk')
                read = "() => JSON.parse(Object.entries(sessionStorage).find(([k])=>k.startsWith('penerimaan-ringkas:'))[1])"
                saved = await page.evaluate(read)
                await form.get_by_role('button', name='Terima ke tujuan', exact=True).click()
                await expect(root.locator('[data-galat]')).to_contain_text('Status pencatatan perlu diperiksa')
                stable = await _sidik(pg)
                gate_asset['next'] = True
                await page.reload(wait_until='commit')
                await asyncio.wait_for(entered.wait(), 15)
                held = await page.evaluate(read)
                assert held['key'] == saved['key'] and held['forms'] == saved['forms']
                assert 'Belum ada penerimaan yang dikirim' not in await root.inner_text()
                asset_release.set()
                recovery = root.locator('[data-pemulihan]')
                await expect(recovery).to_be_visible()
                await recovery.get_by_role('button', name='Baca status penerimaan terbaru', exact=True).click()
                await expect(recovery.locator('[data-hasil-status]')).to_contain_text('Catatan penerimaan terbaru ditemukan')
                final = await page.evaluate(read)
                assert final['key'] == saved['key'] and final['forms'] == saved['forms']
                assert len(bodies) == len(transport['posts']) == 1
                assert bodies[0]['kunci_kiriman'] == saved['key']
                assert await _sidik(pg) == stable
                assert not transport['errors'], transport['errors']
            finally:
                asset_release.set()


@pytest.mark.parametrize('width', [390, 1280])
async def test_asset_daftar_gagal_tetap_ada_jalur_GET_dan_menu(pg, lengkap, width):
    """A failed optional initializer must not leave an inescapable loading row."""
    async with await _klien(pg, role=P.OPERATOR, gudang_id=lengkap['gudang']['g2']) as c:
        before = await _sidik(pg)
        async with peramban(c, width) as (page, transport):
            transport['fail_asset'] = True
            await page.goto(BASE + '/kabar')
            if width < 900:
                await page.locator('#buka-laci').click()
            await page.locator('#laci a[href="/barang-masuk"]').click()
            fallback = page.locator('[data-bm-bootstrap]')
            await expect(fallback).to_be_visible()
            await expect(fallback).to_contain_text('hanya membaca data')
            reload = fallback.get_by_role('link', name='muat ulang halaman')
            await expect(reload).to_have_attribute('href', '/barang-masuk')
            await expect(page.locator('[data-bm-search] input[name=cari]')).to_have_value('')
            # Recover by one user GET, never by a business POST or another controller.
            transport['fail_asset'] = False
            origin_before = await page.evaluate('performance.timeOrigin')
            async with page.expect_navigation(wait_until='domcontentloaded') as navigation:
                await reload.click()
            response = await navigation.value
            assert response is not None and response.status == 200
            await page.wait_for_load_state('load')
            assert await page.evaluate('performance.timeOrigin') != origin_before
            await expect(page.locator('[data-bm-shell]')).to_have_count(0)
            await expect(page.locator('[data-bm-bootstrap]')).to_have_count(0)
            if width < 900:
                button = page.locator('#buka-laci')
                await expect(button).to_have_attribute('aria-expanded', 'false')
                await button.click()
                await expect(button).to_have_attribute('aria-expanded', 'true')
                await expect(page.locator('#laci')).to_be_visible()
                await expect(page.locator('#laci a[href="/kabar"]')).to_be_in_viewport()
            await page.locator('#laci a[href="/kabar"]').click()
            await expect(page).to_have_url(BASE + '/kabar')
            assert not transport['posts']
            assert not transport['errors'], transport['errors']
        assert await _sidik(pg) == before


async def test_pemulihan_belum_commit_kembali_isian_dari_qc(pg,lengkap):
    tid=lengkap['tiket']['GABAH_KERING'];path='/barang-masuk/'+str(tid)
    entered,release=asyncio.Event(),asyncio.Event();job=None;posts=[];status_gets=[];writer_started=False
    async with await _klien(pg,role=P.OPERATOR,gudang_id=lengkap['gudang']['g1']) as c:
        native=c.request
        async def request(method,url,**kw):
            nonlocal job,writer_started
            p=urlsplit(str(url)).path
            if method=='POST':
                assert p=='/api/actions/gabah-masuk';posts.append(json.loads(kw['content']));assert len(posts)==1
                async def delayed_native():
                    nonlocal writer_started
                    await release.wait()
                    writer_started=True
                    return await native(method,url,**kw)
                job=asyncio.create_task(delayed_native());entered.set()
                return await asyncio.shield(job)
            r=await native(method,url,**kw)
            if p=='/api/actions/penerimaan-ringkas/'+str(tid):status_gets.append(r.status_code)
            return r
        c.request=request
        async with peramban(c,390) as (page,transport):
            async def accept_reload(dialog):
                assert dialog.type=='beforeunload';await dialog.accept()
            page.on('dialog',accept_reload)
            try:
                await page.goto(BASE+path)
                root=page.locator('[data-bm-detail-shell]');form=root.locator('[data-formulir] form')
                await expect(form).to_be_visible()
                await form.locator('[name=warehouse_id]').select_option(str(lengkap['gudang']['g1']))
                await form.locator('[name=tujuan]').select_option('tumpuk')
                read="()=>JSON.parse(Object.entries(sessionStorage).find(([k])=>k.startsWith('penerimaan-ringkas:'))[1])"
                original=await page.evaluate(read);before=await _sidik(pg)
                await form.get_by_role('button',name='Terima ke tujuan',exact=True).click()
                await asyncio.wait_for(entered.wait(),15)
                assert posts[0]['kunci_kiriman']==original['key']
                await page.reload()
                recovery=root.locator('[data-pemulihan]');await expect(recovery).to_be_visible()
                restored=await page.evaluate(read)
                assert restored['key']==original['key'] and restored['forms']==original['forms'] and restored['uncertain']
                await recovery.get_by_role('button',name='Baca status penerimaan terbaru',exact=True).click()
                await expect(recovery.locator('[data-hasil-status]')).to_contain_text('Belum ditemukan catatan baru')
                back=recovery.get_by_role('button',name='Kembali ke isian setelah pemeriksaan',exact=True)
                await expect(back).to_be_visible()
                # The native tab is an ordinary button: no request or form clone.
                await root.locator('[data-bm-tab=qc]').focus()
                await page.keyboard.press('Enter')
                await expect(root.locator('[data-bm-detail-panel=qc]')).to_be_visible()
                await expect(form).to_be_hidden()
                await back.focus();await page.keyboard.press('Enter')
                final=await page.evaluate(read)
                assert final['key']==original['key'] and final['forms']==original['forms'] and not final['uncertain']
                assert len(posts)==len(transport['posts'])==1 and status_gets==[200] and not writer_started
                assert await _sidik(pg)==before
                if os.environ.get('PHASE_OUT'):
                    out=Path(os.environ['PHASE_OUT']);engine=os.environ['OWNER_BROWSER']
                    await page.screenshot(path=str(out/(engine+'-after-native-return.png')),full_page=True)
                    (out/(engine+'-native-return-state.json')).write_text(json.dumps({'same_key':True,'same_input':True,'native_return_cleared_uncertain':True,'POST_attempts':1,'POST_commits':0,'auto_resubmit':False,'manual_status_GETs':1,'alltable_fingerprint_unchanged':True,'summary_hidden':await root.locator('[data-bm-detail-panel=ringkasan]').get_attribute('hidden') is not None,'form_visible':await form.is_visible(),'focused_element':await page.evaluate('()=>({tag:document.activeElement.tagName,name:document.activeElement.name||null})'),'limits':'Native POST execution is held before writer only in test; cleanup cancels its unexecuted fixture task. This does not claim a browser cancels real server commit.'},indent=2)+'\n')
                await expect(form).to_be_visible()
                await expect(root.locator('[data-bm-tab=ringkasan]')).to_have_attribute('aria-selected','true')
                await expect(form.locator('[name=warehouse_id]')).to_have_value(str(lengkap['gudang']['g1']))
                await expect(form.locator('[name=tujuan]')).to_have_value('tumpuk')
                await expect(form.locator('[name=warehouse_id]')).to_be_focused()
                assert not transport['errors'],transport['errors']
            finally:
                if job and not job.done():
                    job.cancel();await asyncio.gather(job,return_exceptions=True)


_NATIVE_CLOSE_FOCUS = """(() => {
 const log=[], state={log,cleanupCount:0};window.__bmNativeClose=state;
 function label(n){return {tag:n?.tagName||null,id:n?.id||null,name:n?.name||null};}
 document.addEventListener('focusin',e=>log.push({event:'focusin',node:label(e.target),t:performance.now()}),true);
 document.addEventListener('close',e=>{
  if(e.target.id!=='bm-filter')return;
  state.isTrusted=e.isTrusted;state.beforeIntent=label(document.activeElement);
  // Test-only scheduling of a newer focus intent on the actual trusted event.
  // Do not stop propagation, replay dispatchEvent, or replace native cleanup.
  document.querySelector('[data-bm-search] input[name=cari]').focus();
  log.push({event:'trusted-close-new-intent',trusted:e.isTrusted,active:label(document.activeElement),t:performance.now()});
 },true);
})();"""

@pytest.mark.parametrize('renderer',['native','shell'])
async def test_close_terpercaya_menghormati_fokus_isian(pg,lengkap,renderer):
 entered,release=asyncio.Event(),asyncio.Event()
 async with await _klien(pg,role=P.ADMIN) as c:
  if renderer=='native':
   native=c.request
   async def request(method,url,**kw):
    if str(url).split('?',1)[0]=='/barang-masuk':
     kw['headers']={**kw.get('headers',{}),'X-Pindah':'1'};kw['headers'].pop('x-kerangka-halaman',None)
    return await native(method,url,**kw)
   c.request=request
  before=await _sidik(pg)
  async with peramban(c,390) as (page,transport):
   await page.add_init_script(_NATIVE_CLOSE_FOCUS)
   try:
    if renderer=='shell':
     transport['gates']['/api/halaman-bertahap/barang-masuk']=(entered,release)
     await page.goto(BASE+'/kabar');await page.locator('#buka-laci').click()
     await page.locator('#laci a[href="/barang-masuk"]').click();await asyncio.wait_for(entered.wait(),15)
    else:await page.goto(BASE+'/barang-masuk')
    root=page.locator('[data-bm-page]');await expect(root).to_have_attribute('data-siap','1')
    search=root.locator('[data-bm-search] input[name=cari]')
    await search.fill('Pilihan operator setelah dialog ditutup')
    await root.locator('#bm-filter').evaluate("d=>d.addEventListener('close',()=>{__bmNativeClose.cleanupCount++})")
    await root.locator('.kontrol-filter').click();await expect(root.locator('#bm-filter')).to_be_visible()
    await page.keyboard.press('Escape')
    await page.wait_for_function('__bmNativeClose.cleanupCount===1')
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    result=await page.evaluate("()=>({timeline:__bmNativeClose.log,isTrusted:__bmNativeClose.isTrusted,beforeIntent:__bmNativeClose.beforeIntent,native_cleanup_count:__bmNativeClose.cleanupCount,active:{tag:document.activeElement.tagName,id:document.activeElement.id,name:document.activeElement.name||null},value:document.querySelector('[data-bm-search] input[name=cari]').value})")
    result.update(renderer=renderer,source='actual browser trusted close; document capture sets newer focus only, native handlers run unchanged',business_POSTs=len(transport['posts']),tables_unchanged=await _sidik(pg)==before)
    if os.environ.get('PHASE_OUT'):
     engine=os.environ.get('UJI_BROWSER',os.environ.get('OWNER_BROWSER','chromium'))
     (Path(os.environ['PHASE_OUT'])/(engine+'-'+renderer+'-trusted-close-timeline.json')).write_text(json.dumps(result,indent=2)+'\n')
    assert result['isTrusted'] and result['native_cleanup_count']==1 and not transport['posts'] and result['tables_unchanged']
    await expect(search).to_be_focused();await expect(search).to_have_value('Pilihan operator setelah dialog ditutup')
    release.set()
    if renderer=='shell':
     await expect(root.locator('[data-bm-read-status]')).to_contain_text('Isian pilihan tetap dipertahankan');await expect(search).to_be_focused()
    assert not transport['errors'],transport['errors']
   finally:release.set()
  assert await _sidik(pg)==before
