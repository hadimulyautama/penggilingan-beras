"""PROPOSAL ONLY: Root adopts under tests/pg and runs serial after fixture cleanup.

22 pytest nodes per engine (44 for Chromium + WebKit), no xfail/skip. This file
has NOT been run/collected against PG or a browser. Existing ASGI/peramban blocks
service workers: deterministic interception acceptance, not cold/warm PWA.

Recipes are existing PK/QC dunia, PK-karung dunia+batch_baru, sosoh_jasa and
its existing detail-test broken output, and dua_gudang. All setup/actor creation
uses those approved synthetic recipes BEFORE table fingerprints. No setup POST
is sent from a browser and no alternate role, bind, tenant or guard is invented.

Critical expected values always come from native same-URL X-Pindah:1 GET, NOT
from the new shell. H1, bar, breadcrumbs and column differences are accumulated
and FAIL after read/leave/fingerprint evidence has been captured. In particular,
PK native body H1 differs from its title block; do not weaken that assertion to
'Stok'. Untested partial UI states are not a claim of production readiness.
"""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup

from tests.pg.test_stok_g2_per_kode import dunia as pk_dunia
from tests.pg.test_pk_karung import dunia as karung_dunia, batch_baru
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_layar_gudang_http import dua_gudang
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE

pytestmark = pytest.mark.asyncio
NATIVE = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
DOCUMENT = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
SHELL = '[data-stock-detail-native]'
LINKS = ('a.stok-baris__tautan[href],a.stok-mobile-list__baris[href],'
         '.produk-list a.tabel-standar__baris[href],a.alur-gudang__buka[href]')
ROLES = ('admin', 'operator-g1', 'operator-g2')
WIDTHS = (1280, 390)


def native_semantics(html):
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    assert main, 'Actual native content boundary missing'
    crumb = main.select_one('.desktop-chrome__crumbrow')
    bar = main.select_one('header.bar')
    assert crumb and bar, 'Actual native chrome missing'
    items = []
    for li in crumb.select('nav.desktop-breadcrumb ol > li'):
        item = li.select_one('a[href],[aria-current="page"]')
        assert item
        items.append((item.name, item.get_text(' ', strip=True),
                      item.get('href'), item.get('aria-current')))
    def control(node):
        return None if node is None else dict(tag=node.name,
            text=node.get_text(' ', strip=True), href=node.get('href'),
            label=node.get('aria-label'), title=node.get('title'))
    detail = main.select_one('main.pk-detail') or main
    return dict(
        h1=[n.get_text(' ', strip=True) for n in detail.select('h1')],
        bar=control(bar.select_one('.bar__merek')),
        mobile=control(bar.select_one('.bar__balik,.bar__menu')),
        crumbs=items, back=control(crumb.select_one('a.desktop-back')),
        columns=[[n.get_text(' ', strip=True) for n in table.select('thead th')]
                 for table in detail.select('table') if table.select('thead th')],
        fields=[n.get_text(' ', strip=True) for n in detail.select('dt')],
        controls=[control(n) for n in detail.select(
            '.pk-detail__actions a,.pk-detail__actions button,'
            '.alur-tahap a,.alur-stok>a')])


async def role_client(pg, role):
    """Reuse existing actor recipe; only its existing native warehouse IDs."""
    from sqlalchemy import select
    from app.models import Warehouse
    warehouse = None
    if role.startswith('operator-'):
        async with pg() as db:
            rows = (await db.scalars(select(Warehouse.id).where(
                Warehouse.kode_fungsi == role.rsplit('-', 1)[1]))).all()
            assert len(rows) == 1, 'Fixture must have one existing matching warehouse; do not create/bind another.'
            warehouse = rows[0]
    client = await _klien(pg, role='admin' if role == 'admin' else 'operator',
                          gudang_id=warehouse)
    client.base_url = BASE
    return client


def read_gate(transport, path):
    entered, release = asyncio.Event(), asyncio.Event()
    transport['gate_headers'][path] = {'x-pindah': '1', 'x-kerangka-halaman': '0'}
    transport['gates'][path] = entered, release
    return entered, release


async def frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def choose_link(page, source, wanted):
    await page.goto(BASE + source, wait_until='load')
    await page.wait_for_function('()=>window.PadiKerangkaStockDetailUI&&document.getElementById("padi-stock-detail-catalog")', timeout=20000)
    host = page.locator('#padi-stock-detail-catalog')
    assert await host.count() == 1
    catalog = json.loads(await host.text_content())
    matches = [entry for entry in catalog['entries'] if wanted(entry['alamat'])]
    assert len(matches) == 1, dict(source=source, targets=[e['alamat'] for e in matches])
    target = matches[0]['alamat']
    links = page.locator(LINKS)
    visible = []
    for index in range(await links.count()):
        node = links.nth(index)
        if await node.get_attribute('href') == target and await node.is_visible():
            visible.append(node)
    assert len(visible) == 1, dict(source=source, target=target, visible=len(visible))
    return target, visible[0]


async def negative_catalog_controls(page, target):
    """Only mutate transient DOM metadata, restore exactly; no request/storage."""
    return await page.evaluate('''target=>{
      const host=document.getElementById('padi-stock-detail-catalog');
      const registry=JSON.parse(document.getElementById('padi-kerangka-langsung').textContent);
      const base=registry.frames['/barang-masuk'].map(i=>registry.potongan[i]).join('');
      const frame=document.querySelector('.bingkai'),cap=document.documentElement.dataset.versi,
            ctx=frame.dataset.pindahKonteks,token=document.getElementById('formulir-sesi').dataset.token;
      const call=()=>window.PadiKerangkaStockDetailUI.buat(target,base,ctx,cap,token);
      const original=host.textContent,parent=host.parentNode,next=host.nextSibling,positive=!!call(),result={positive};
      for(const key of ['cap','konteks','sesi','sumber','asal','asal_sha256']){
        const bad=JSON.parse(original);bad[key]=key==='asal_sha256'?'0'.repeat(64):'owner-negative';
        host.textContent=JSON.stringify(bad);result[key]=call()===null;
      }
      host.textContent=original;
      const selected=[...document.querySelectorAll('a[href]')].filter(n=>n.getAttribute('href')===target);
      const states=selected.map(n=>n.hidden);selected.forEach(n=>n.hidden=true);
      result.hidden=call()===null;selected.forEach((n,i)=>n.hidden=states[i]);
      host.remove();result.missing=call()===null;parent.insertBefore(host,next);
      result.restored=!!call();return result;
    }''', target)


def evidence_folder(role, width, family):
    value = os.getenv('DETAIL_OUT')
    if not value:
        return None
    out = Path(value) / ('stock-detail-' + family + '-' + role + '-' + str(width))
    out.mkdir(parents=True, exist_ok=True)
    return out


async def exercise(page, transport, client, source, wanted, *, out, label):
    """Positive actual visible offer, strict native parity, then late GET leave."""
    from playwright.async_api import expect
    target, link = await choose_link(page, source, wanted)
    native = await client.get(target, headers=NATIVE)
    assert native.status_code == 200
    expected = native_semantics(native.text)
    negatives = await negative_catalog_controls(page, target)
    failures = []
    if not all(negatives.values()):
        failures.append(dict(phase='catalog-negative', actual=negatives))
    path = urlsplit(target).path
    read_start = transport['gets'].count(path)
    entered, release = read_gate(transport, path)
    shell_semantics = after = None
    try:
        await link.press('Enter')
        await asyncio.wait_for(entered.wait(), 20)
        await expect(page.locator(SHELL)).to_be_visible()
        assert transport['gets'].count(path) - read_start == 1, 'First-click made duplicate native reads'
        await expect(page.locator('.halaman-memuat')).to_have_count(0)
        assert await page.locator(SHELL+' form,'+SHELL+' input,'+SHELL+' textarea').count() == 0
        assert await page.locator(SHELL+' [data-kirim],'+SHELL+' [data-post],'+SHELL+' script[type="application/json"]').count() == 0
        assert await page.locator(SHELL+' button:not(:disabled):not([data-stock-detail-retry])').count() == 0
        before_html = await page.content()
        shell_semantics = native_semantics(before_html)
        # Fields that need amounts are unread, not fabricated zero/empty rows.
        await expect(page.locator(SHELL+' [data-stock-detail-status]')).to_contain_text('Memuat')
        for key in ('h1', 'bar', 'mobile', 'crumbs', 'back'):
            if shell_semantics[key] != expected[key]:
                failures.append(dict(phase='before-data', field=key,
                    expected=expected[key], actual=shell_semantics[key]))
        # Exactly one approved pending-only exception: QC row presence and
        # history/latest header are absent from the actual list DTO. Seven
        # native invariant headers remain strict; eighth says unknown. This
        # does NOT waive the native columns/true-empty oracle AFTER fresh GET.
        from app.web.stock_detail_native import native_table_headers
        pending_doc=BeautifulSoup(before_html,'html.parser')
        qc=pending_doc.select_one('[data-stock-qc-shape="unread"] table')
        if qc is not None:
            invariant=native_table_headers()['qc']+['Catatan · menunggu data']
            actual=[n.get_text(' ',strip=True) for n in qc.select('thead th')]
            if actual!=invariant or 'belum diketahui kosong atau berisi' not in qc.select_one('tbody').text:
                failures.append(dict(phase='before-data-qc-unknown',expected=invariant,actual=actual))
            qc.decompose()
            native_doc=BeautifulSoup(native.text,'html.parser')
            for n in native_doc.select('table[aria-label="Riwayat QC stok PK"]'):n.decompose()
            actual_columns=native_semantics(str(pending_doc))['columns']
            expected_columns=native_semantics(str(native_doc))['columns']
        else:
            actual_columns=shell_semantics['columns'];expected_columns=expected['columns']
        if actual_columns!=expected_columns:
            failures.append(dict(phase='before-data-invariant-columns',expected=expected_columns,actual=actual_columns))
        if out:
            await page.screenshot(path=str(out/(label+'-before-data.png')), full_page=True)
        release.set()
        await expect(page.locator(SHELL)).to_have_count(0, timeout=20000)
        after = native_semantics(await page.content())
        if after != expected:
            failures.append(dict(phase='after-data', expected=expected, actual=after))
        if out:
            await page.screenshot(path=str(out/(label+'-after-data.png')), full_page=True)
    finally:
        release.set()
    # Start another actual read, then use the actually visible native Back.
    target2, link2 = await choose_link(page, source, wanted)
    assert target2 == target
    entered2, release2 = read_gate(transport, path)
    try:
        await link2.click()
        await asyncio.wait_for(entered2.wait(), 20)
        await expect(page.locator(SHELL)).to_be_visible()
        back = page.locator('.bar__balik:visible,.desktop-back:visible').first
        assert await back.count() == 1
        destination = await back.get_attribute('href')
        assert destination and destination.startswith('/')
        await back.press('Enter')
        await expect(page).to_have_url(BASE+destination, timeout=20000)
        await expect(page.locator(SHELL)).to_have_count(0)
        release2.set()
        await frames(page)
        await expect(page).to_have_url(BASE+destination)
        await expect(page.locator(SHELL)).to_have_count(0)
    finally:
        release2.set()
    return dict(label=label, source=source, target=target, native=expected,
                before=shell_semantics, after=after, negatives=negatives,
                failures=failures, leave_late=True)


async def run_cases(pg, client, role, width, family, cases):
    """All read/cancel work is bracketed by a full-table stable fingerprint."""
    out = evidence_folder(role, width, family)
    before = await _sidik(pg)
    results = []
    try:
        async with peramban(client, width) as (page, transport):
            for source, wanted, label in cases:
                results.append(await exercise(page, transport, client, source,
                    wanted, out=out, label=label))
            assert not transport['posts'], transport['posts']
            assert not transport['errors'], transport['errors']
    finally:
        assert await _sidik(pg) == before, 'GET/navigation changed native tables'
        if out:
            (out/'observations.json').write_text(json.dumps(dict(role=role,
                width=width, engine=os.getenv('UJI_BROWSER',os.getenv('OWNER_BROWSER','chromium')),
                results=results), ensure_ascii=False, indent=2))
    failures = [dict(case=r['label'], detail=f) for r in results for f in r['failures']]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)


def pk_target(warehouse, key):
    def wanted(url):
        q = parse_qs(urlsplit(url).query)
        return q.get('gudang') == [warehouse] and q.get('kode' if warehouse=='g1' else 'id') == [str(key)]
    return wanted


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('width', WIDTHS)
async def test_pk_g1_g2_curah_actual_native_structure_scope_and_leave(pg, pk_dunia, role, width):
    async with await role_client(pg, role) as client:
        cases = [('/stok?pemilik=pabrik',pk_target('g1','LOT-KODE-01'),'pk-g1')]
        path = f'/stok/pk/detail?gudang=g2&id={pk_dunia["giling_intake_id"]}'
        denied = role == 'operator-g1'
        for headers in (NATIVE,DOCUMENT):
            response = await client.get(path,headers=headers)
            assert response.status_code == (404 if denied else 200)
            if denied:
                assert not BeautifulSoup(response.text,'html.parser').select(SHELL+',script[data-stock-detail-read]')
        if not denied:
            cases.append(('/stok?pemilik=pabrik',pk_target('g2',pk_dunia['giling_intake_id']),'pk-g2-curah'))
        await run_cases(pg,client,role,width,'pk',cases)


@pytest.mark.parametrize('role', ('admin','operator-g2'))
@pytest.mark.parametrize('width', WIDTHS)
async def test_pk_purchased_bags_actual_variant_not_inferred(pg, karung_dunia, role, width):
    # Unchanged native recipe: 128 bags nominal80, measured10140, one intake.
    async with pg() as db:
        _,_,intake = await batch_baru(db,karung_dunia)
        iid = intake.id
    async with await role_client(pg,role) as client:
        await run_cases(pg,client,role,width,'pk-karung',[
            ('/stok?pemilik=pabrik',pk_target('g2',iid),'pk-g2-karung')])


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('width', WIDTHS)
async def test_products_native_medium_auto_broken_and_jasa_scope(pg, sosoh_jasa, role, width):
    # EXACT existing test_stok_produk_detail recipe for an additional byproduct,
    # no fake card/ORM substitute or edited product reader.
    from sqlalchemy import select
    from app.database import now_local
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingOutputLog
    async with pg() as db:
        source = await db.scalar(select(PolishingProcess).where(
            PolishingProcess.kode_proses==sosoh_jasa['kode_pabrik']))
        db.add(PolishingOutputLog(polishing_process_id=source.id,jenis='broken',
            berat_kg=125,waktu_update=now_local(),input_by=sosoh_jasa['user']))
        await db.commit()
    async with await role_client(pg,role) as client:
        paths = ['/stok-produk/detail?jenis=medium','/stok-produk/detail?jenis=broken',
                 f'/stok-produk-jasa/detail?jenis=medium&pelanggan_id={sosoh_jasa["pelanggan_id"]}']
        if role == 'operator-g1':
            before = await _sidik(pg)
            for path in paths:
                for headers in (DOCUMENT,NATIVE):
                    response = await client.get(path,headers=headers)
                    assert response.status_code == 404
                    assert not BeautifulSoup(response.text,'html.parser').select(SHELL+',script[data-stock-detail-read]')
            assert await _sidik(pg)==before
            return
        wanted=lambda kind,jasa=False: lambda url: (
            urlsplit(url).path==('/stok-produk-jasa/detail' if jasa else '/stok-produk/detail')
            and parse_qs(urlsplit(url).query).get('jenis')==[kind])
        await run_cases(pg,client,role,width,'products',[
            ('/stok-produk',wanted('medium'),'product-medium'),
            ('/stok-produk',wanted('broken'),'product-broken'),
            ('/stok-produk-jasa',wanted('medium',True),'product-jasa-medium')])


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('width', WIDTHS)
async def test_home_actual_authorized_warehouse_offers_and_other_scope_denied(pg,dua_gudang,role,width):
    async with await role_client(pg,role) as client:
        before=await _sidik(pg)
        cases=[]
        for gid in ('g1','g2'):
            path='/gudang/'+gid
            allowed=role=='admin' or role=='operator-'+gid
            for headers in (DOCUMENT,NATIVE):
                response=await client.get(path,headers=headers)
                assert response.status_code==(200 if allowed else 403)
                if not allowed:
                    assert not BeautifulSoup(response.text,'html.parser').select(SHELL+',script[data-stock-detail-read]')
            if allowed:
                cases.append(('/',lambda url,path=path:url==path,'warehouse-'+gid))
        assert await _sidik(pg)==before
        await run_cases(pg,client,role,width,'warehouse',cases)
