"""Prepared OWNER acceptance, not scheduled QA. NOT EXECUTED by author.

Adopt this file into tests/pg only after Root review/all-source freeze. Reuses
native customer A/B, alur/catatan/transaksi and portal_browser actual cookies +
X-Portal headers. No new identity/role/company type, no fake auth/data success.
These customers are two ownership scopes, NOT two company tenants. SW is
blocked for deterministic holds; PWA/Safari/hosted are separate gates.
"""
from __future__ import annotations
import asyncio
from urllib.parse import urlsplit
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect
from tests.pg.test_portal_pelanggan import portal, client
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_portal_transaksi_detail import transaksi
from tests.pg.test_portal_catatan import catatan
from tests.pg.test_portal_alur_hp import alur
from tests.pg.test_portal_kerangka_browser import (
    portal_browser, menu_click, stable_paint, screenshot, BASE, DATA,
)
from tests.pg.test_halaman_bertahap import _sidik
from app.web.portal.detail_kerangka import TABS
pytestmark=pytest.mark.asyncio
FRAME='[data-portal-detail-frame]'
FOREIGN=('Rahasia Pelanggan B','LOT-RAHASIA-B','LOT-CATATAN-RAHASIA','Rahasia seluruh pabrik')


def address(href):
    u=urlsplit(href)
    return u.path+('?' +u.query if u.query else '')


def families(alur):
    return [('giling','/pelanggan/jasa-saya',alur['giling']),
            ('penerimaan','/pelanggan/barang-masuk',alur['masuk_detail'])]


async def native(c,href):
    r=await c.get(address(href),headers=DATA)
    assert r.status_code==200
    assert 'no-store' in r.headers.get('cache-control','')
    s=BeautifulSoup(r.text,'html.parser');main=s.select_one('#isi-pelanggan')
    assert main and not main.select(FRAME)
    assert len(main.select('h1'))==1
    return s


async def ready(page):
    await page.wait_for_function('()=>window.PORTAL_NAV&&window.PadiKerangkaPortalUI&&window.PadiKerangkaPortalDetailUI')


async def source_page(page,source,width):
    await menu_click(page,source,width)
    await expect(page.locator('[data-portal-native-frame]')).to_have_count(0)
    assert address(page.url)==source


async def source_link(page,target):
    link=page.locator('#isi-pelanggan a[href="'+target+'"]')
    await expect(link).to_have_count(1)
    await expect(link).to_be_visible()
    return link


async def open_native_tabs(page,kind):
    # Giling's actual read-only tabs sit in a native disclosure, initially
    # folded on Ringkasan. Use the ordinary UI, never force visibility.
    if kind=='giling':
        fold=page.locator('#isi-pelanggan details.pelanggan-proses-lanjutan')
        await expect(fold).to_have_count(1)
        if await fold.get_attribute('open') is None:
            await fold.locator(':scope > summary').click()


async def assert_frame(page,kind,expected,target,*,initial=False):
    frame=page.locator(FRAME)
    await expect(frame).to_be_visible()
    await expect(frame.locator('h1')).to_have_text(expected.select_one('#isi-pelanggan h1').get_text(' ',strip=True))
    await expect(frame).to_have_attribute('data-portal-address',address(target))
    await expect(frame.locator('[role=tab]')).to_have_text([label for _,label in TABS[kind]])
    assert not await frame.locator('form,input,[name=_csrf],[data-post],[data-kirim]').count()
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    assert await page.title()==expected.title.get_text()
    if initial:
        # Only the visible source link exists at first click; no fabricated
        # resource tab hrefs may be used before native detail data returns.
        disabled=frame.locator('[role=tab][disabled]')
        await expect(disabled).to_have_count(3)
        for node in await disabled.all():
            await expect(node).to_be_disabled()
            await expect(node).to_have_attribute('aria-describedby','portal-detail-wait')
    text=await page.locator('#isi-pelanggan').inner_text()
    assert all(v not in text for v in FOREIGN)
    return frame


async def assert_native(page,expected):
    await expect(page.locator(FRAME)).to_have_count(0)
    await expect(page.locator('#isi-pelanggan h1')).to_have_text(expected.select_one('#isi-pelanggan h1').get_text(' ',strip=True))
    assert await page.title()==expected.title.get_text()
    text=await page.locator('#isi-pelanggan').inner_text()
    assert all(v not in text for v in FOREIGN)
    assert not await page.locator('#isi-pelanggan form[method=post],#isi-pelanggan [data-post],#isi-pelanggan [data-kirim]').count()


async def release(gate):
    gate.release.set()
    await asyncio.wait_for(gate.done.wait(),25)


@pytest.mark.parametrize('width',[390,1280])
async def test_portal_deep_actual_parent_links_tabs_and_missing_link_cache_policy(pg,portal,alur,width):
    async with client(portal.accounts[0]) as c:
        async with portal_browser(c,width) as (page,control):
            await page.goto(BASE+'/pelanggan/kabar',wait_until='load');await ready(page)
            before=await _sidik(pg)
            for kind,source,target in families(alur):
                expected=await native(c,target)
                await source_page(page,source,width)
                html=control.hold(address(target),'html');data=control.hold(address(target),'data')
                try:
                    await (await source_link(page,target)).click()
                    await asyncio.wait_for(data.entered.wait(),25)
                    await assert_frame(page,kind,expected,target,initial=True)
                    # Two negotiation phases are held independently. An adopted
                    # first click needs NO target HTML; native data is pending.
                    assert not html.entered.is_set()
                    assert control.count(address(target),'html')==0
                    assert control.count(address(target),'data')==1
                    assert [r for r in control.seen if r['address']==address(target) and r['phase']=='data'][-1]['portal_header']=='1'
                    await screenshot(page,'portal-deep-'+kind+'-pending-'+str(width))
                    await release(data);await assert_native(page,expected)
                finally:
                    html.release.set();data.release.set();control.gates.pop((address(target),'html'),None)
                for key,label in TABS[kind]:
                    await open_native_tabs(page,kind)
                    # Exact identity by aria-controls prevents Ringkasan text
                    # or another link elsewhere becoming a substitute.
                    prefix='panel-' if kind=='giling' else 'terima-panel-'
                    tab=page.locator('#isi-pelanggan a[role=tab][aria-controls="'+prefix+key+'"]')
                    href=await tab.get_attribute('href');assert href
                    await expect(tab).to_have_text(label);await expect(tab).to_be_visible()
                    expected_tab=await native(c,href)
                    if kind=='giling':
                        result=await page.evaluate('href=>{const u=new URL(href,location.href);const good=PadiKerangkaPortalDetailUI.siap(href);u.hash="#panel-not-declared";const bad=u.pathname+u.search+u.hash;return {good,bad:PadiKerangkaPortalDetailUI.siap(bad),frame:PadiKerangkaPortalDetailUI.buat(bad)!==null};}',href)
                        assert result=={'good':True,'bad':False,'frame':False}
                    pending=control.hold(address(href),'data')
                    try:
                        await tab.press('Enter');await asyncio.wait_for(pending.entered.wait(),25)
                        frame=await assert_frame(page,kind,expected_tab,href)
                        panel=frame.locator('[data-portal-detail-panel="'+key+'"]')
                        await expect(panel).to_be_visible()
                        if kind=='penerimaan' and key=='qc':
                            await expect(panel.locator('table thead th')).to_have_text(['Parameter','Hasil pemeriksaan'])
                            await expect(panel.locator('table tbody tr')).to_have_count(1)
                        elif kind=='penerimaan' and key=='riwayat':
                            await expect(panel.locator('table thead th')).to_have_text(['Kode barang','Berat','Status','Waktu penerimaan'])
                        elif kind=='giling' and key=='hasil':
                            await expect(panel.locator('table')).to_have_count(2)
                            await expect(panel.locator('table').first.locator('thead th')).to_have_text(['Waktu','PK kumulatif','Pencatat'])
                            await expect(panel.locator('table').nth(1).locator('thead th')).to_have_text(['Putaran / waktu','Hasil pemeriksaan','Nilai kualitas','Kondisi / catatan lab','Pencatat'])
                        assert not control.posts
                        await release(pending);await assert_native(page,expected_tab)
                    finally:pending.release.set()
                # A canonical direct read may have been visited, but is absent
                # from this detail's exact tab links. URL classification must
                # bypass old HTML caching WITHOUT granting an invented frame.
                checks=await page.evaluate('u=>({ready:PadiKerangkaPortalDetailUI.siap(u),frame:PadiKerangkaPortalDetailUI.buat(u)!==null,fresh:PadiKerangkaPortalDetailUI.freshOnly(u),link:[...document.querySelectorAll("#isi-pelanggan a[href]")].some(a=>a.getAttribute("href")===u)})',target)
                assert checks=={'ready':False,'frame':False,'fresh':True,'link':False}
                await page.evaluate('()=>{const n=document.createElement("p");n.dataset.ownerRetainedProbe="";n.textContent="Penanda lokal sebelum GET segar";document.getElementById("isi-pelanggan").append(n);}')
                pending=control.hold(address(target),'data')
                try:
                    await page.evaluate('u=>{window.PORTAL_NAV.buka(u);}',target)
                    await asyncio.wait_for(pending.entered.wait(),25)
                    await expect(page.locator('[data-owner-retained-probe]')).to_be_visible()
                    await expect(page.locator(FRAME)).to_have_count(0)
                    await release(pending);await assert_native(page,expected)
                    await expect(page.locator('[data-owner-retained-probe]')).to_have_count(0)
                finally:pending.release.set()
            assert not control.posts and not control.errors,dict(posts=control.posts,errors=control.errors)
            assert await _sidik(pg)==before


@pytest.mark.parametrize('width',[390,1280])
async def test_portal_deep_503_explicit_retry_stale_leave_and_back_only_read(pg,portal,alur,width):
    async with client(portal.accounts[0]) as c:
        async with portal_browser(c,width) as (page,control):
            await page.goto(BASE+'/pelanggan/kabar',wait_until='load');await ready(page)
            before=await _sidik(pg)
            for kind,source,target in families(alur):
                expected=await native(c,target)
                await source_page(page,source,width)
                control.fail_once.add((address(target),'data'))
                await (await source_link(page,target)).click()
                frame=page.locator(FRAME)
                await expect(frame.locator('[data-portal-read-retry]')).to_be_visible()
                await expect(frame.locator('h1')).to_have_text(expected.select_one('#isi-pelanggan h1').get_text(' ',strip=True))
                await expect(frame.locator('[role=tab]')).to_have_count(4)
                retry=control.hold(address(target),'data')
                try:
                    await frame.locator('[data-portal-read-retry]').press('Enter')
                    await asyncio.wait_for(retry.entered.wait(),25)
                    await expect(frame.locator('[data-portal-read-retry]')).to_be_hidden()
                    await release(retry);await assert_native(page,expected)
                finally:retry.release.set()
                await source_page(page,source,width)
                late=control.hold(address(target),'data')
                try:
                    await (await source_link(page,target)).click();await asyncio.wait_for(late.entered.wait(),25)
                    await assert_frame(page,kind,expected,target,initial=True)
                    await menu_click(page,'/pelanggan/laporan',width)
                    await expect(page.locator('[data-portal-native-frame]')).to_have_count(0)
                    await expect(page.locator('#isi-pelanggan h1')).to_have_text('Dokumen')
                    await release(late);await stable_paint(page)
                    await expect(page.locator('#isi-pelanggan h1')).to_have_text('Dokumen')
                    assert address(page.url)=='/pelanggan/laporan'
                finally:late.release.set()
                back=control.hold(address(target),'data')
                try:
                    # Back has no currently selected native detail source link;
                    # it may keep the old page until fresh data, never revive
                    # stale cached resource HTML or invent permission.
                    await page.go_back(wait_until='commit')
                    await asyncio.wait_for(back.entered.wait(),25)
                    assert not control.posts
                    await release(back);await assert_native(page,expected)
                    assert address(page.url)==address(target)
                finally:back.release.set()
            assert not control.posts and not control.errors,dict(posts=control.posts,errors=control.errors)
            assert await _sidik(pg)==before


async def test_portal_deep_original_customer_B_denies_A_resource_and_data_headers(pg,portal,alur):
    # Native ASGI guard proof, deliberately separate from browser width claims.
    async with client(portal.accounts[0]) as a:
        targets=[]
        for kind,_,target in families(alur):
            s=await native(a,target);targets.append((target,s))
        before=await _sidik(pg)
        async with client(portal.accounts[1]) as b:
            for target,s in targets:
                hrefs=[target,*[n['href'] for n in s.select('#isi-pelanggan a[role=tab][href]')]]
                for href in hrefs:
                    # Exact A-native tabs carry A's selector; B must not be
                    # treated as A merely because the browser knows a URL.
                    r=await b.get(address(href),headers=DATA)
                    assert r.status_code==404
                    assert not BeautifulSoup(r.text,'html.parser').select(FRAME)
                    assert s.select_one('#isi-pelanggan h1').get_text(' ',strip=True) not in r.text
            for target,_ in targets:
                r=await a.get(address(target),headers={**DATA,'X-Kerangka-Halaman':'1','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
                assert r.status_code==200 and not BeautifulSoup(r.text,'html.parser').select(FRAME)
            assert await _sidik(pg)==before
