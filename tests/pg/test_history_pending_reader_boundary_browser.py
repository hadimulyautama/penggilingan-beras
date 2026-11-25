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
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect
from sqlalchemy import select

from app.models import MillingProcess, Warehouse
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_history_detail_owner_browser import (
    BASE, READY, SHELL, _klien, gate, native_golden, actual_link, source_ready,
    peramban, two_frames,
    giling_selesai, hasil, g1, sosoh_selesai, running, dunia,
)

pytestmark = pytest.mark.asyncio
TARGET = '/barang-masuk'
DATA_TARGET = '/api/halaman-bertahap/barang-masuk'


class PhaseLedger:
    """Bounded literal diagnostics; no HTML, route IDs, values or keys."""
    def __init__(self,kind,width,mode):
        names={
          ('giling',1280,'navigate'):'giling-admin-desktop-navigate',
          ('giling',390,'navigate'):'giling-operator-mobile-navigate',
          ('giling',1280,'penanda-refresh'):'giling-admin-desktop-penanda',
          ('giling',390,'penanda-refresh'):'giling-operator-mobile-penanda',
          ('sosoh',1280,'navigate'):'sosoh-admin-desktop-navigate',
          ('sosoh',390,'navigate'):'sosoh-operator-mobile-navigate',
          ('sosoh',1280,'penanda-refresh'):'sosoh-admin-desktop-penanda',
          ('sosoh',390,'penanda-refresh'):'sosoh-operator-mobile-penanda',
        }
        self.case=names[(kind,width,mode)];self.started=time.monotonic();self.count=0
        self.path=Path(os.environ['DETAIL_OUT'])/('history-pending-phases-'+self.case+'.jsonl') if os.environ.get('DETAIL_OUT') else None
    def phase(self,name):
        assert type(name) is str and name and len(name)<=80 and all(c.isalpha() or c in '.-' for c in name)
        self.count+=1;assert self.count<=128
        if self.path:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a') as stream:
                stream.write(json.dumps({'phase':name,'monotonic_seconds':round(time.monotonic()-self.started,6)})+'\n')
                stream.flush()


async def finish_actions(actions,ledger):
    """All gate releases happen before this bounded action drain."""
    if not actions:return
    done,pending=await asyncio.wait(actions,timeout=20)
    if pending:
        ledger.phase('cleanup.action-timeout')
        for task in pending:task.cancel()
        await asyncio.wait(pending,timeout=5)
    errors=[]
    for task in done:
        if not task.cancelled():
            try:task.result()
            except Exception as error:errors.append(error)
    assert not pending,'Owner browser action did not complete after gate release'
    if errors:raise errors[0]


async def open_history_pending(page,transport,client,item,releases,actions,ledger):
    # Own release before starting the action; a regressed full navigation must
    # not hide that release behind an await of the gated keyboard operation.
    ledger.phase('history.source-ready.begin')
    await asyncio.wait_for(source_ready(page,item['source']),35)
    ledger.phase('history.source-ready.end')
    link=await actual_link(page,item['path'],item['code'],item['family'])
    original=BeautifulSoup(await native_golden(client,item['source']),'html.parser')
    assert any(a.get('href')==item['path'] and item['code'] in a.get_text() for a in original.select('a[href]'))
    assert await page.evaluate("""target=>{
      const frame=document.querySelector('.bingkai'),token=document.getElementById('formulir-sesi')?.dataset.token,cap=document.documentElement.dataset.versi;
      try{const r=JSON.parse(document.getElementById('padi-kerangka-langsung').textContent),base=r.frames['/barang-masuk'].map(i=>r.potongan[i]).join('');
       return !!window.PadiKerangkaRiwayatDetailUI.buat(target,base,frame.dataset.pindahKonteks,cap,token);
      }catch(_){return false;}
    }""",item['path'])
    entered,release,completed=gate(transport,item['path']);releases.append(release)
    actions.append(asyncio.create_task(link.press('Enter',no_wait_after=True,timeout=30000)))
    ledger.phase('history.press-started')
    await asyncio.wait_for(entered.wait(),20)
    ledger.phase('history.data-held')
    await expect(page.locator(SHELL)).to_be_visible()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    return release,completed


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


def native_history_contract(html, kind, *, editor):
    """Admin tetap editor native; Operator terbukti sebagai pembaca murni."""
    assert kind in {'giling', 'sosoh'} and type(editor) is bool
    doc = BeautifulSoup(html, 'html.parser')
    roots = doc.select('[data-riwayat-' + kind + ']')
    assert len(roots) == 1
    root = roots[0]
    assert root.has_attr('data-editor-perintah') is editor
    assert root.has_attr('data-history-readonly') is (not editor)
    if editor:
        assert root.select_one('.riwayat-koreksi__form') is not None
    else:
        assert root['data-history-readonly'] == '1'
        assert not root.select('form,[name],[data-rhs-edit],[data-kirim],[data-aksi],[data-buka-aksi],[data-qc-editor],[data-qc-jenis],[data-qc-lengkapi],[data-qc-baru]')
        assert not doc.select('script[src*="qc-sosoh.js"],script[src*="koreksi-bahan-berjalan"],script[src*="koreksi-di-detail"]')
        assert all(not tag.get('data-buka') and not tag.get('data-nilai') for tag in doc.select('script[data-buka]'))
    return True


async def prepare_native_admin_draft(page):
    """Actual local review only: no confirmation/POST and no fixture write."""
    await page.locator('[data-rhs-edit]:visible').first.click()
    form = page.locator('.riwayat-koreksi__form')
    field = form.locator('input[type=number][name^="hasil_"]').first
    value = await field.input_value()
    assert value and float(value) >= 0
    await field.fill(str(float(value) + 0.25))
    await form.locator('[name=alasan]').fill('Draf sintetis pemeriksaan navigasi; belum disimpan')
    await form.locator('button[type=submit]:visible').first.click()
    await expect(form.locator('[data-rhs-review]')).to_be_visible()
    await expect(form.locator('[data-rhs-confirm]')).to_be_visible()
    assert await form.evaluate("f=>{const r=f.closest('[data-riwayat-giling],[data-riwayat-sosoh]'),m=window[r.hasAttribute('data-riwayat-giling')?'PADI_RIWAYAT_GILING_DRAF':'PADI_RIWAYAT_SOSOH_DRAF'];return m[r.dataset.rhsActor+'|'+f.querySelector('[name=_csrf]').value].form===f;}")


async def remember_native_identity(page, kind, *, editor):
    selector = '[data-riwayat-' + kind + ']'
    native = page.locator(selector)
    await expect(native).to_be_visible()
    await expect(native).to_have_attribute('data-rhs-ready', '1')
    assert native_history_contract(await page.content(), kind, editor=editor)
    # Same key calculation as the UNCHANGED actual native design controller.
    # Keep all synthetic token/value material inside this disposable browser;
    # return booleans only, never credentials/CSRF/field values in artifacts.
    valid = await page.evaluate("""({kind,editor})=>{
      const root=document.querySelector('[data-riwayat-'+kind+']'),
       memory=window[kind==='giling'?'PADI_RIWAYAT_GILING_DRAF':'PADI_RIWAYAT_SOSOH_DRAF'],
       form=root.querySelector('.riwayat-koreksi__form'),
       key=root.dataset.rhsActor+'|'+(form?.querySelector('[name=_csrf]')?.value||'');
      if(!memory||!Object.hasOwn(memory,key))return false;
      const values=Array.from(form?.elements||[]).map(node=>[node,node.value]),
       storage=Object.keys(sessionStorage).filter(k=>/koreksi|draft|draf|pending/i.test(k))
        .map(k=>[k,sessionStorage.getItem(k)]);
      if(!!form!==editor)return false;
      window.__historyPendingOwner={root,memory,key,entry:memory[key],form,values,storage,editor};
      return true;
    }""", dict(kind=kind,editor=editor))
    assert valid


async def assert_native_identity_preserved(page):
    valid = await page.evaluate("""()=>{
      const s=window.__historyPendingOwner;
      return !!s&&s.root.isConnected&&s.root.hasAttribute('data-editor-perintah')===s.editor&&
       s.root.hasAttribute('data-history-readonly')===!s.editor&&
       s.memory[s.key]===s.entry&&(!s.form||s.form.isConnected)&&
       s.values.every(([node,value])=>node.isConnected&&node.value===value)&&
       s.storage.every(([key,value])=>sessionStorage.getItem(key)===value)&&
       Object.keys(sessionStorage).filter(k=>/koreksi|draft|draf|pending/i.test(k)).length===s.storage.length;
    }""")
    assert valid


def bm_native_semantics(html):
    doc=BeautifulSoup(html,'html.parser');main=doc.select_one('#isi-halaman');root=main.select_one('[data-bm-page]')
    assert root is not None and not root.has_attr('data-bm-shell')
    return dict(title=doc.title.get_text(' ',strip=True),
        brand=main.select_one('header.bar .bar__merek').get_text(' ',strip=True),
        headings=[n.get_text(' ',strip=True) for n in main.select('h1')],
        columns=[[n.get_text(' ',strip=True) for n in h.select('th')] for h in root.select('[data-bm-results] thead')],
        controls=sorted({(n.name,n.get('name'),n.get('type','')) for n in root.select('input[name],select[name],textarea[name]')}))


async def native_editor_veto_control(page, transport, releases, actions, ledger, destination_golden):
    """After data, existing REAL editor marker still forces native document.

    A full document waiting for HTML is intentional here. This negative
    control must not be marketed as all-pages first-click readiness.
    """
    entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    transport['gates'][TARGET] = (entered, release)
    transport['gate_headers'][TARGET] = {}
    transport['completed'][TARGET] = completed
    releases.append(release)
    action=None
    observed,request_seen=asyncio.Event(),asyncio.Event()
    snapshots,requests=[],[]
    prefix='owner-history-native-veto:'
    def console_snapshot(message):
        if not message.text.startswith(prefix):return
        value=json.loads(message.text[len(prefix):])
        assert type(value) is dict and set(value)=={
            'oldRoot','editorMarker','draftEntry','form','values','storage','bmAbsent'}
        assert all(type(v) is bool for v in value.values())
        snapshots.append(value);observed.set()
    async def classify_request(request):
        headers=await request.all_headers()
        requests.append(dict(
            get=request.method=='GET',document=request.resource_type=='document',
            navigation=request.is_navigation_request(),
            exactAddress=request.url==BASE+TARGET,
            nativeDoc=headers.get('sec-fetch-dest')=='document',
            nativeMode=headers.get('sec-fetch-mode')=='navigate',
            noPindah='x-pindah' not in headers,
            noShape='x-kerangka-halaman' not in headers))
        request_seen.set()
    def request_snapshot(request):
        if urlsplit(request.url).path==TARGET:
            actions.append(asyncio.create_task(classify_request(request)))
    page.on('console',console_snapshot)
    page.on('request',request_snapshot)
    try:
        link = await menu_link(page)
        # Capture only booleans synchronously on the REAL anchor, before its
        # default document navigation. Never stop, replace or cancel the event.
        # DOM RPC after a provisional native navigation can wait for new HTML;
        # the externally retained snapshot avoids that fixture-only deadlock.
        await link.evaluate("""(link,prefix)=>link.addEventListener('click',()=>{
          const s=window.__historyPendingOwner,
           keys=Object.keys(sessionStorage).filter(k=>/koreksi|draft|draf|pending/i.test(k));
          console.info(prefix+JSON.stringify({
            oldRoot:!!s&&s.root.isConnected,
            editorMarker:!!s&&s.root.hasAttribute('data-editor-perintah'),
            draftEntry:!!s&&s.memory[s.key]===s.entry,
            form:!!s&&(!s.form||s.form.isConnected),
            values:!!s&&s.values.every(([node,value])=>node.isConnected&&node.value===value),
            storage:!!s&&keys.length===s.storage.length&&s.storage.every(([key,value])=>sessionStorage.getItem(key)===value),
            bmAbsent:document.querySelectorAll('[data-bm-page]').length===0
          }));
        },{capture:true,once:true,passive:true})""",prefix)
        ledger.phase('native-veto.capture-ready')
        action=asyncio.create_task(link.press('Enter',no_wait_after=True,timeout=30000))
        actions.append(action)
        ledger.phase('native-veto.press-started')
        await asyncio.wait_for(entered.wait(),20)
        ledger.phase('native-veto.html-held')
        await asyncio.wait_for(observed.wait(),20)
        await asyncio.wait_for(request_seen.wait(),20)
        assert not release.is_set()
        assert len(snapshots)==1 and all(snapshots[0].values()),snapshots
        # The route bridge does not always receive browser Sec-Fetch headers.
        # Browser protocol metadata still proves this is an exact ordinary
        # document navigation, not an X-Pindah or native reader fetch. Explicit
        # server DOCUMENT-header semantics are covered by separate tests.
        required=('get','document','navigation','exactAddress','noPindah','noShape')
        assert len(requests)==1 and all(requests[0][key] for key in required),requests
        ledger.phase('native-veto.before-html-asserted')
    finally:
        # No DOM RPC runs while full document HTML remains withheld.
        release.set()
        page.remove_listener('console',console_snapshot)
        page.remove_listener('request',request_snapshot)
        ledger.phase('native-veto.html-released')
    if action is not None:
        await asyncio.wait_for(asyncio.shield(action),20)
        ledger.phase('native-veto.action-complete')
    await asyncio.wait_for(completed.wait(),20)
    await page.wait_for_function("()=>location.pathname==='/barang-masuk'")
    # Normal document is no longer held. Wait for its actual native readout,
    # not a transient shell that may already have hydrated and disappeared.
    await page.wait_for_function("""()=>{
      const root=document.querySelector('#isi-halaman [data-bm-page]:not([data-bm-shell])'),results=root?.querySelector('[data-bm-results]');
      return !!results&&!results.hasAttribute('aria-busy')&&!root.querySelector('[data-bm-error]:not([hidden])');
    }""",timeout=20000)
    assert bm_native_semantics(await page.content())==bm_native_semantics(destination_golden)
    assert await page.evaluate("""()=>{
      const frame=document.querySelector('.bingkai'),session=document.getElementById('formulir-sesi'),root=document.querySelector('#isi-halaman [data-bm-page]');
      return !!frame&&!!session?.dataset.token&&frame.dataset.pindahAlamat===location.pathname+location.search&&root.dataset.bmContext===frame.dataset.pindahKonteks&&root.dataset.bmCap===document.documentElement.dataset.versi;
    }""")
    ledger.phase('native-veto.destination-native-ready')


async def native_readonly_nonblocking_control(page, transport, releases, actions, ledger, destination_golden):
    """The hydrated real Operator reader has no writer to veto navigation."""
    await assert_native_identity_preserved(page)
    html_entered, html_release = asyncio.Event(), asyncio.Event()
    data_entered, data_release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    releases.extend([html_release, data_release])
    transport['gates'][TARGET] = (html_entered, html_release)
    transport['gate_headers'][TARGET] = {}
    transport['gates'][DATA_TARGET] = (data_entered, data_release)
    transport['completed'][DATA_TARGET] = completed
    count_html = transport['gets'].count(TARGET)
    try:
        link = await menu_link(page)
        actions.append(asyncio.create_task(link.press('Enter',no_wait_after=True,timeout=30000)))
        ledger.phase('native-readonly.menu-press-started')
        await asyncio.wait_for(data_entered.wait(),20)
        await expect(page.locator('[data-bm-page]')).to_be_visible()
        await expect(page.locator('[data-bm-results] th')).to_have_count(6)
        await expect(page.locator('.halaman-memuat')).to_have_count(0)
        assert not html_entered.is_set()
        assert transport['gets'].count(TARGET) == count_html
        assert await page.evaluate("""()=>{
          const s=window.__historyPendingOwner,
           keys=Object.keys(sessionStorage).filter(k=>/koreksi|draft|draf|pending/i.test(k));
          return !!s&&!s.editor&&!s.form&&!s.root.isConnected&&s.memory[s.key]===s.entry&&
           keys.length===s.storage.length&&s.storage.every(([key,value])=>sessionStorage.getItem(key)===value);
        }""")
        ledger.phase('native-readonly.before-data-and-html-asserted')
    finally:
        data_release.set();html_release.set()
        transport['gates'].pop(TARGET,None)
    await asyncio.wait_for(completed.wait(),20)
    await page.wait_for_function("""()=>{
      const root=document.querySelector('#isi-halaman [data-bm-page]:not([data-bm-shell])'),results=root?.querySelector('[data-bm-results]');
      return !!results&&!results.hasAttribute('aria-busy')&&!root.querySelector('[data-bm-error]:not([hidden])');
    }""",timeout=20000)
    assert bm_native_semantics(await page.content()) == bm_native_semantics(destination_golden)
    ledger.phase('native-readonly.destination-native-ready')


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
    ledger=PhaseLedger(item['kind'],width,mode)
    ledger.phase('case.begin')
    client.base_url = BASE
    ledger.phase('baseline.native-read.begin')
    golden = await asyncio.wait_for(native_golden(client,item['path']),30)
    ledger.phase('baseline.native-read.end')
    editor = item['native_editor']
    assert native_history_contract(golden, item['kind'], editor=editor)
    ledger.phase('baseline.destination-native-read.begin')
    destination_golden=await asyncio.wait_for(native_golden(client,TARGET),30)
    bm_native_semantics(destination_golden)
    ledger.phase('baseline.destination-native-read.end')
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
    ledger.phase('baseline.fingerprint.begin')
    before = await asyncio.wait_for(_sidik(pg),30)
    ledger.phase('baseline.fingerprint.end')
    releases,actions = [],[]
    ledger.phase('browser.open.begin')
    async with peramban(client,width) as (page,transport):
        ledger.phase('browser.open.end')
        failed=False
        try:
            async with asyncio.timeout(120):
                ledger.phase('history.initial-open')
                old_release,old_completed=await open_history_pending(page,transport,client,item,releases,actions,ledger)
                ledger.phase('history.pending-shape.assert')
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
                    actions.append(asyncio.create_task(link.press('Enter',no_wait_after=True,timeout=30000)))
                    ledger.phase('navigate.menu-press-started')
                    await asyncio.wait_for(data_entered.wait(),20)
                    ledger.phase('navigate.destination-data-held')
                    await expect(page.locator('[data-bm-page]')).to_be_visible()
                    await expect(page.locator('[data-bm-results] th')).to_have_count(6)
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    await expect(page.locator(SHELL)).to_have_count(0)
                    assert not html_entered.is_set()
                    assert transport['gets'].count(TARGET) == count_html
                    ledger.phase('navigate.before-data-and-html-asserted')
                    old_release.set()
                    ledger.phase('navigate.old-data-released')
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
                    ledger.phase('history.reopen')
                    release,completed=await open_history_pending(page,transport,client,item,releases,actions,ledger)
                    release.set()
                    await asyncio.wait_for(completed.wait(), 20)
                    await expect(page.locator(READY)).to_be_visible()
                    await remember_native_identity(page,item['kind'],editor=editor)
                    ledger.phase('history.reopen.native-identity-ready')
                else:
                    assert mode == 'penanda-refresh'
                    # Establish native baseline AFTER pending frame installed,
                    # because native pasang() resets its private penanda to null.
                    ledger.phase('penanda.baseline.begin')
                    await consume_native_penanda(page)
                    ledger.phase('penanda.baseline.consumed')
                    assert signal['reads'] >= 1
                    refresh_entered, refresh_release, refresh_completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                    releases.append(refresh_release)
                    transport['gates'][item['path']] = (refresh_entered, refresh_release)
                    transport['gate_headers'][item['path']] = {'x-pindah': '1'}
                    transport['completed'][item['path']] = refresh_completed
                    signal['changed'] = True
                    ledger.phase('penanda.change.begin')
                    await consume_native_penanda(page)
                    ledger.phase('penanda.change.consumed')
                    await asyncio.wait_for(refresh_entered.wait(),20)
                    ledger.phase('penanda.refresh-held')
                    await assert_pending_has_no_editor(page)
                    refresh_release.set()
                    await asyncio.wait_for(refresh_completed.wait(), 20)
                    await remember_native_identity(page,item['kind'],editor=editor)
                    ledger.phase('penanda.refresh-native-ready')
                    # The refresh returned the actual native reader/editor for
                    # this role. Its identity/keys survive the older held read.
                    transport['completed'][item['path']] = old_completed
                    old_release.set()
                    await asyncio.wait_for(old_completed.wait(), 20)
                    await two_frames(page)
                    await expect(page.locator(SHELL)).to_have_count(0)
                    await assert_native_identity_preserved(page)
                    assert signal['reads'] >= 2
                    assert any(path == item['path'] and x == '1' and flag is None for _, path, x, flag in trace)
                if editor:
                    await prepare_native_admin_draft(page)
                    await remember_native_identity(page,item['kind'],editor=True)
                    ledger.phase('native-editor.actual-draft-reviewed')
                    await native_editor_veto_control(page,transport,releases,actions,ledger,destination_golden)
                    ledger.phase('native-veto.complete')
                else:
                    await native_readonly_nonblocking_control(page,transport,releases,actions,ledger,destination_golden)
                    ledger.phase('native-readonly.complete')
                assert not transport['posts'] and not transport['errors'], transport
                assert all(method == 'GET' for method, *_ in trace)
        except TimeoutError:
            failed=True;ledger.phase('case.timeout')
            raise
        except BaseException:
            failed=True;ledger.phase('case.failure')
            raise
        finally:
            ledger.phase('cleanup.release-all')
            for release in releases:release.set()
            try:
                await finish_actions(actions,ledger)
                ledger.phase('cleanup.actions-drained')
            except BaseException:
                ledger.phase('cleanup.action-failure')
                if not failed:raise
            finally:ledger.phase('browser.close.begin')
    ledger.phase('browser.closed')
    ledger.phase('final.fingerprint.begin')
    assert await asyncio.wait_for(_sidik(pg),30)==before
    ledger.phase('case.pass')


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
@pytest.mark.parametrize('mode', ['navigate', 'penanda-refresh'])
async def test_giling_pending_reader_can_leave_but_real_editor_keeps_its_boundary(pg, giling_selesai, width, role, mode, monkeypatch):
    _, process = giling_selesai
    async with pg() as db:
        stored = await db.scalar(select(MillingProcess).where(MillingProcess.id == process.id))
        item = dict(name='giling-' + role, kind='giling', path='/riwayat-giling/' + str(stored.id),
                    code=stored.kode_proses, source='/riwayat-giling', family='history',native_editor=role=='admin')
    async with await _klien(pg, peran=role, gudang='Gudang 1') as client:
        await exercise(pg, client, item, width, monkeypatch, mode)


@pytest.mark.parametrize('width,role', [(1280, 'admin'), (390, 'operator')], ids=['admin-desktop','operator-390'])
@pytest.mark.parametrize('mode', ['navigate', 'penanda-refresh'])
async def test_sosoh_pending_reader_can_leave_but_real_editor_keeps_its_boundary(pg, sosoh_selesai, width, role, mode, monkeypatch):
    # The native Admin destination reads both canonical warehouses. The Sosoh
    # fixture supplies only G2. Add only the missing canonical master row from
    # the product seed recipe BEFORE fingerprints; no actor, role, binding,
    # stock, silo, process or existing G2 row is changed.
    from app.services.seed import _WAREHOUSES
    async with pg() as db:
        existing=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        if existing is None:
            code,name=next(pair for pair in _WAREHOUSES if pair[0]=='g1')
            db.add(Warehouse(kode_fungsi=code,nama_gudang=name))
            await db.commit()
    item = dict(name='sosoh-' + role, kind='sosoh', path='/riwayat-sosoh/' + str(sosoh_selesai['id']),
                code=sosoh_selesai['kode'], source='/riwayat-sosoh', family='history',native_editor=role=='admin')
    async with await _klien(pg, peran=role, gudang='Gudang 2') as client:
        await exercise(pg, client, item, width, monkeypatch, mode)
