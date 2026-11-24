"""PREPARED owner acceptance for staff return READ layouts; not executed.

Existing native recipes only: `asal` -> 10 whole25kg bags accepted from the
500kg original shipment. This is NOT the held partial20/50kg proposal/PACK.
Existing native account helpers supply the same Admin or ordinary Operator G2;
no dependency override, role escalation, binding recipe or browser setup POST.
All fixture setup completes before the full-table fingerprint.

Real route: sidebar Pengiriman -> Barang Retur tab (`retur` is intentionally
hidden in the sidebar). R1 uses one same-URL X-Pindah:1 nativeHTML/data response,
not an HTML-then-JSON chain. We hold that actual HTML response after native auth
and read, assert framework before release and record no earlier document fetch.
Do not report this as two independent network stages or a real HTTP/PWA proof.
`peramban` is the existing in-process ASGI bridge with service_workers=block.
Native detail tabs are local after hydration: the test must not invent a GET.
RTP builder/caller is not wired in R1: direct native document boundary only.
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
from sqlalchemy import select

from app.models import Warehouse
from tests.pg.test_retur_pengajuan import asal,simpan,selesai,terima
from tests.pg.test_barang_keluar import _klien as existing_account
from tests.pg.test_stok_pk_g1_polesan import _klien as existing_operator_account
from tests.pg.test_portal_pelanggan import portal,client as portal_client
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_barang_masuk_bertahap_browser import BASE,peramban
from tests.pg.test_halaman_bertahap import _sidik

pytestmark=pytest.mark.asyncio
NATIVE={'X-Pindah':'1','X-Kerangka-Halaman':'0'}
DOCUMENT={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
SHELL='[data-retur-baca-native]'
READY='[data-retur-baca-isi]'
TABS=('ringkasan','barang','tiket','riwayat')
TABLES=[['Pengiriman asal','Pelanggan','Tiket timbang','Pemeriksaan'],['Penerimaan / tanggal','Pelanggan','Nomor polisi','Tiket timbang','Berat diterima','Selisih']]
ITEMS=['Barang / merek','Mutu','Kemasan','Jumlah kemasan','Berat','Catatan','Catatan stok']


def address(value):
    parsed=urlsplit(value)
    assert not parsed.netloc or parsed.netloc=='uji'
    return parsed.path+('?' +parsed.query if parsed.query else '')


def semantic(html):
    """Native same-URL is the oracle, not a generic title or the new shell."""
    doc=BeautifulSoup(html,'html.parser');main=doc.select_one('#isi-halaman');assert main is not None
    bar=main.select_one('header.bar');brand=bar.select_one('.bar__merek');control=bar.select_one('.bar__menu,.bar__balik');assert brand is not None and control is not None
    crumbs=main.select_one('.desktop-chrome__crumbrow');assert crumbs is not None
    trail=[]
    for item in crumbs.select('nav.desktop-breadcrumb ol>li'):
        node=item.select_one('a[href],[aria-current=page]');assert node is not None
        trail.append(dict(tag=node.name,text=node.get_text(' ',strip=True),href=node.get('href'),current=node.get('aria-current')))
    back=crumbs.select_one('a.desktop-back');body_back=main.select_one('.detail-kirim-kembali')
    return dict(title=doc.title.get_text(),brand=brand.get_text(' ',strip=True),brand_label=brand.get('aria-label'),
        control=dict(tag=control.name,id=control.get('id'),classes=control.get('class'),href=control.get('href'),label=control.get('aria-label')),
        crumbs=trail,back=None if back is None else dict(href=back.get('href'),label=back.get('aria-label')),
        h1=[n.get_text(' ',strip=True) for n in main.select('h1')],
        columns=[[n.get_text(' ',strip=True) for n in head.select('th')] for head in main.select('table thead')],
        body_back=None if body_back is None else dict(href=body_back.get('href'),text=body_back.get_text(' ',strip=True)))


def gate(transport,path):
    entered,release,completed=asyncio.Event(),asyncio.Event(),asyncio.Event()
    transport['gate_headers'][path]={'x-pindah':'1','x-kerangka-halaman':'0'}
    transport['gates'][path]=(entered,release);transport['completed'][path]=completed
    return entered,release,completed


async def frames(page):await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


def artifact(name,width):
    root=os.environ.get('DETAIL_OUT')
    if not root:return None
    path=Path(root)/('retur-read-'+name+'-'+str(width));path.mkdir(parents=True,exist_ok=True);return path


async def admin(pg,world,name):
    account=await existing_account(pg,world['uid'],'owner_retur_read_'+name)
    account.base_url=BASE
    return account


async def accepted(pg,world):
    # Exactly the ordinary existing full-bag native flow, before fingerprints.
    application=await simpan(pg,world,10)
    await selesai(pg,world)
    receipt=await terima(pg,application.id)
    assert receipt is not None and receipt.berat_rincian_kg==250
    return int(receipt.id)


async def golden(client,path):
    response=await client.get(path,headers=NATIVE);assert response.status_code==200,(path,response.status_code)
    doc=BeautifulSoup(response.text,'html.parser');assert not doc.select(SHELL)
    return response.text


def trace_reads(client,monkeypatch,*,fault=None):
    trace=[];original=client.request
    async def recorded(method,url,**kwargs):
        response=await original(method,url,**kwargs)
        headers={k.lower():v for k,v in kwargs.get('headers',{}).items()};path=urlsplit(str(url)).path
        trace.append(dict(method=method.upper(),path=path,pindah=headers.get('x-pindah'),kerangka=headers.get('x-kerangka-halaman'),document=headers.get('sec-fetch-mode')=='navigate' and headers.get('sec-fetch-dest')=='document'))
        if fault is not None and fault['next'] and path==fault['path'] and method.upper()=='GET' and headers.get('x-pindah')=='1' and headers.get('x-kerangka-halaman')=='0':
            assert response.status_code==200
            fault['next']=False;fault['count']+=1
            # Explicitly failed read transport AFTER actual authorization/read.
            # No fake success DTO, status policy or fixture business row.
            return httpx.Response(503,text='Owner synthetic read unavailable',headers={'content-type':'text/html'},request=response.request)
        return response
    monkeypatch.setattr(client,'request',recorded)
    return trace


async def shipping_menu(page,width):
    await page.goto(BASE+'/kabar',wait_until='load')
    if width<900:await page.locator('#buka-laci').click()
    link=page.locator('#laci a[href="/barang-keluar"]')
    await expect(link).to_be_visible();await link.press('Enter')
    await expect(page).to_have_url(BASE+'/barang-keluar')
    await page.wait_for_function("()=>!!window.PadiKerangkaReturBacaUI&&!!document.getElementById('padi-retur-baca-kerangka')")
    tab=page.locator('#isi-halaman .kontrol-tab a[href="/retur"]:visible')
    await expect(tab).to_have_count(1)
    return tab


async def receipt_link(page,client,rid):
    await page.goto(BASE+'/retur',wait_until='load')
    await page.wait_for_function("()=>!!window.PadiKerangkaReturBacaUI&&!!document.getElementById('padi-retur-baca-catalog')")
    host=json.loads(await page.locator('#padi-retur-baca-catalog').text_content())
    matches=[entry for entry in host['entries'] if entry['kind']=='receipt' and entry['id']==rid]
    assert len(matches)==1;entry=matches[0]
    target=entry['target'];assert target==f'/retur/{rid}'
    native=BeautifulSoup(await golden(client,'/retur'),'html.parser')
    native_links=[a for a in native.select('[data-retur-receipts] td[data-sel="utama"]>a.tabel-standar__kode[href]') if a.get('href')==target and a.get_text()==entry['code']]
    assert len(native_links)==1
    link=page.locator('[data-retur-receipts] td[data-sel="utama"]>a.tabel-standar__kode[href="'+target+'"]')
    await expect(link).to_have_count(1);await expect(link).to_be_visible()
    return target,link


async def read_ready(page):
    try:
        await expect(page.locator(SHELL)).to_have_count(0,timeout=20000)
    except AssertionError as error:
        # Only the read-status text; never dump secret-bearing native HTML.
        status=await page.locator(SHELL+' [data-retur-baca-status]').inner_text()
        raise AssertionError('Retur native read not installed: '+status) from error
    await expect(page.locator(READY)).to_be_visible()


async def inert_shape(page):
    root=page.locator(SHELL);await expect(root).to_be_visible()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    assert await root.locator('form,input,select,textarea,[name],[data-post],[data-kirim]').count()==0
    assert await root.locator('button:not(:disabled):not([data-retur-baca-retry])').count()==0
    await expect(root.locator('[data-retur-baca-status]')).to_contain_text('Memuat')
    for hidden in await root.locator('[hidden]').all():await expect(hidden).to_be_hidden()


@pytest.mark.parametrize('width',[390,1280])
async def test_actual_shipping_tab_list_before_native_html_and_two_empty_tables(pg,asal,width,monkeypatch):
    async with await admin(pg,asal,'empty_'+str(width)) as client:
        native=await golden(client,'/retur');expected=semantic(native)
        assert expected['h1']==[] and expected['columns']==TABLES
        trace=trace_reads(client,monkeypatch);before=await _sidik(pg);out=artifact('empty',width)
        async with peramban(client,width) as (page,transport):
            entered,release,completed=gate(transport,'/retur')
            try:
                tab=await shipping_menu(page,width);await tab.press('Enter')
                await asyncio.wait_for(entered.wait(),20)
                await inert_shape(page)
                # Framework is present before releasing the actual native HTML.
                assert semantic(await page.content())==expected
                assert not [r for r in trace if r['path']=='/retur' and r['document']],trace
                reads=[r for r in trace if r['path']=='/retur'];assert reads and all(r['pindah']=='1' and r['kerangka']=='0' for r in reads)
                if out:await page.screenshot(path=str(out/'before-native-html.png'),full_page=True)
                release.set();await asyncio.wait_for(completed.wait(),20);await read_ready(page)
                assert semantic(await page.content())==expected
                root=page.locator(READY)
                for selector,n,note in [('[data-retur-applications]',4,'Tidak ada pengajuan retur menunggu pemeriksaan.'),('[data-retur-receipts]',6,'Belum ada penerimaan retur.')]:
                    section=root.locator(selector);await expect(section.locator('thead th')).to_have_count(n)
                    await expect(section.locator('tbody tr')).to_have_count(1)
                    await expect(section.locator('tbody td')).to_have_attribute('colspan',str(n));await expect(section.locator('tbody td')).to_have_text(note)
                if out:await page.screenshot(path=str(out/'after-native-html.png'),full_page=True)
                assert not transport['posts'] and not transport['errors'],dict(posts=transport['posts'],errors=transport['errors'])
            finally:release.set()
        assert await _sidik(pg)==before
        if out:(out/'observations.json').write_text(json.dumps(dict(width=width,native=expected,requests=trace,html_and_data_same_native_get=True,not_http_pwa=True),indent=2))


@pytest.mark.parametrize('width',[390,1280])
async def test_actual_accepted_receipt_row_four_tabs_native_chrome_back_and_document_boundary(pg,asal,width):
    rid=await accepted(pg,asal)
    async with await admin(pg,asal,'receipt_'+str(width)) as client:
        path=f'/retur/{rid}';native=await golden(client,path);expected=semantic(native)
        assert expected['columns']==[ITEMS]
        # The RTP actual link comes from mutable application; no R1 early
        # document/caller adoption is claimed or fabricated for this route.
        for target in [path,f'/retur/tiket/{asal["tiket"][0]}']:
            for headers in [DOCUMENT,NATIVE]:
                response=await client.get(target,headers=headers);assert response.status_code==200
                assert not BeautifulSoup(response.text,'html.parser').select(SHELL)
        before=await _sidik(pg);out=artifact('receipt',width)
        async with peramban(client,width) as (page,transport):
            target,link=await receipt_link(page,client,rid)
            entered,release,completed=gate(transport,path)
            try:
                await link.press('Enter');await asyncio.wait_for(entered.wait(),20)
                await inert_shape(page)
                assert semantic(await page.content())==expected
                await expect(page.locator(SHELL+' table thead th')).to_have_text(ITEMS)
                await expect(page.locator(SHELL+' [role=tab]')).to_have_text(['Ringkasan','Barang','Tiket & bobot','Riwayat'])
                if out:await page.screenshot(path=str(out/'receipt-before-data.png'),full_page=True)
                release.set();await asyncio.wait_for(completed.wait(),20);await read_ready(page)
                assert semantic(await page.content())==expected
                for tab in TABS:
                    count=transport['gets'].count(path)
                    control=page.locator(READY+' [data-detail-tab] #tab-'+tab)
                    await control.press('Enter')
                    await expect(control).to_have_attribute('aria-selected','true')
                    await expect(page.locator(READY+' #panel-'+tab)).to_be_visible()
                    await frames(page)
                    assert transport['gets'].count(path)==count,'Hydrated native tabs must not add a GET'
                    actual=address(await control.get_attribute('href'));assert semantic(await page.content())==semantic(await golden(client,actual))
                await page.locator(READY+' #tab-ringkasan').focus();await page.keyboard.press('ArrowRight')
                await expect(page.locator(READY+' #tab-barang')).to_be_focused();await expect(page.locator(READY+' #tab-barang')).to_have_attribute('aria-selected','true')
                await page.keyboard.press('Home');await expect(page.locator(READY+' #tab-ringkasan')).to_be_focused()
                back=page.locator(READY+' .detail-kirim-kembali');destination=address(await back.get_attribute('href'))
                assert destination==expected['body_back']['href']
                await back.press('Enter');await expect(page).to_have_url(BASE+destination)
                await read_ready(page);await expect(page.locator('[data-detail-tab]')).to_have_count(0)
                if out:await page.screenshot(path=str(out/'native-back.png'),full_page=True)
                assert not transport['posts'] and not transport['errors'],dict(posts=transport['posts'],errors=transport['errors'])
            finally:release.set()
        assert await _sidik(pg)==before


@pytest.mark.parametrize('width',[390,1280])
async def test_receipt_read_503_keyboard_retry_and_late_response_after_native_back(pg,asal,width,monkeypatch):
    rid=await accepted(pg,asal);path=f'/retur/{rid}'
    async with await admin(pg,asal,'edges_'+str(width)) as client:
        expected=semantic(await golden(client,path));fault=dict(next=False,path=path,count=0);trace=trace_reads(client,monkeypatch,fault=fault)
        before=await _sidik(pg);releases=[];out=artifact('edges',width)
        async with peramban(client,width) as (page,transport):
            try:
                target,link=await receipt_link(page,client,rid);fault['next']=True
                entered,release,completed=gate(transport,path);releases.append(release)
                await link.press('Enter');await asyncio.wait_for(entered.wait(),20);await inert_shape(page)
                release.set();await asyncio.wait_for(completed.wait(),20)
                retry=page.locator(SHELL+' [data-retur-baca-retry]');await expect(retry).to_be_visible()
                await expect(page.locator(SHELL+' [data-retur-baca-status]')).to_have_attribute('role','alert')
                assert semantic(await page.content())==expected
                assert not transport['posts']
                await retry.focus();await page.keyboard.press('Enter');await read_ready(page)
                assert fault['count']==1 and semantic(await page.content())==expected
                # Reopen only through the actual currently authorized list row.
                target,link=await receipt_link(page,client,rid)
                entered,release,completed=gate(transport,path);releases.append(release)
                await link.press('Enter');await asyncio.wait_for(entered.wait(),20);await inert_shape(page)
                leave=page.locator(SHELL+' .detail-kirim-kembali');destination=address(await leave.get_attribute('href'))
                await leave.press('Enter');await expect(page).to_have_url(BASE+destination);await read_ready(page)
                release.set();await asyncio.wait_for(completed.wait(),20);await frames(page)
                await expect(page).to_have_url(BASE+destination)
                await expect(page.locator(SHELL+', [data-detail-tab]')).to_have_count(0)
                assert await page.locator('.bingkai').get_attribute('data-pindah-alamat')==destination
                assert semantic(await page.content())==semantic(await golden(client,destination))
                if out:await page.screenshot(path=str(out/'late-completion-kept-parent.png'),full_page=True)
                assert not transport['posts'] and not transport['errors'],dict(posts=transport['posts'],errors=transport['errors'])
            finally:
                for release in releases:release.set()
        assert await _sidik(pg)==before
        if out:(out/'observations.json').write_text(json.dumps(dict(width=width,read_failures=fault['count'],requests=trace,stale_leave=True,no_post=True),indent=2))


async def test_native_operator_financial_denial_and_no_staff_return_frames(pg,asal):
    rid=await accepted(pg,asal)
    async with pg() as db:
        warehouses=(await db.scalars(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))).all()
        assert len(warehouses)==1,'Use the original native fixture warehouse; do not create or bind another.'
    async with await existing_operator_account(pg,role='operator',gudang_id=warehouses[0]) as client:
        client.base_url=BASE;before=await _sidik(pg)
        for path in ['/retur',f'/retur/{rid}',f'/retur/tiket/{asal["tiket"][0]}']:
            for headers in [NATIVE,DOCUMENT]:
                response=await client.get(path,headers=headers);assert response.status_code==403,(path,response.status_code)
                assert not BeautifulSoup(response.text,'html.parser').select(SHELL+',#padi-retur-baca-kerangka,#padi-retur-baca-catalog')
        async with peramban(client,390) as (page,transport):
            await page.goto(BASE+'/barang-keluar',wait_until='load')
            await expect(page.locator('#isi-halaman .kontrol-tab a[href="/retur"]:visible')).to_have_count(0)
            response=await page.goto(BASE+'/retur',wait_until='load');assert response.status==403
            await expect(page.locator(SHELL+',#padi-retur-baca-kerangka,#padi-retur-baca-catalog')).to_have_count(0)
            assert not transport['posts'] and not transport['errors']
        assert await _sidik(pg)==before


@pytest.mark.parametrize('width',[390,1280])
async def test_customer_native_returns_decline_staff_family_without_new_binding(pg,portal,width):
    # Separate existing portal/qc recipe; not combined with `asal` warehouses.
    async with portal_client(portal.accounts[0]) as client:
        client.base_url=BASE;before=await _sidik(pg)
        response=await client.get('/pelanggan/retur',headers=NATIVE);assert response.status_code==200
        parsed=BeautifulSoup(response.text,'html.parser')
        assert not parsed.select(SHELL+',#padi-retur-baca-kerangka,#padi-retur-baca-catalog')
        assert 'Rahasia Pelanggan B' not in response.text
        async with peramban(client,width) as (page,transport):
            await page.goto(BASE+'/pelanggan/retur',wait_until='load')
            await expect(page.locator('#isi-pelanggan')).to_be_visible()
            await expect(page.locator(SHELL+',#padi-retur-baca-kerangka,#padi-retur-baca-catalog')).to_have_count(0)
            assert not transport['posts'] and not transport['errors']
        assert await _sidik(pg)==before
