"""Owner portal framework acceptance, using original native CustomerReaders.

No account/binding/role is added outside tests.pg.test_portal_pelanggan.portal.
Real browser X-Portal-Navigasi/Sec-Fetch headers reach the ASGI app unchanged;
positive HTML/data is never fabricated. SW is blocked for interception only.
Ordinary HTTP and real cold/warm PWA proof remain separate owner gates.
"""
from __future__ import annotations
import asyncio,os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import Error as BrowserError,async_playwright,expect
from tests.profil_browser import mesin,konteks
from tests.pg.test_portal_pelanggan import portal,client
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_halaman_bertahap import _sidik
from app.web.portal.kerangka import PAGES,aset
pytestmark=pytest.mark.asyncio
BASE='https://uji'
MENU=[('/pelanggan'+path,info['title']) for path,info in PAGES.items()]
DOC={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
DATA={'X-Portal-Navigasi':'1'}

class Hold:
    def __init__(self):
        self.entered=asyncio.Event();self.release=asyncio.Event();self.done=asyncio.Event()

class Control:
    def __init__(self):
        self.gates={};self.holds=[];self.fail_once=set();self.seen=[];self.posts=[];self.errors=[]
    def hold(self,address,phase):
        assert phase in {'html','data'}
        gate=Hold();self.gates[(address,phase)]=gate;self.holds.append(gate);return gate
    def count(self,address,phase):
        return sum(r['address']==address and r['phase']==phase for r in self.seen)

@asynccontextmanager
async def portal_browser(c,width):
    """Reuse native fixture identity and the existing browser profile.

    Staff peramban drops X-Portal-Navigasi in its allowlist, so it would test
    another server protocol. Forward portal headers with this narrow helper;
    the actual fixture client's signed cookie is revalidated in the real app.
    """
    assert (await c.get('/pelanggan/kabar',headers=DATA)).status_code==200
    control=Control();jobs=set();callbacks=set();closing=False
    async with async_playwright() as pw:
        browser=await mesin(pw).launch()
        context=await browser.new_context(**{**konteks(pw,width,900),'service_workers':'block'})
        await context.add_cookies([dict(name=x.name,value=x.value,url=BASE) for x in c.cookies.jar])
        page=await context.new_page()
        page.on('pageerror',lambda e:control.errors.append(str(e)))
        async def route(route):
            owner=asyncio.current_task();callbacks.add(owner);gate=None;job=None
            request=route.request;u=urlsplit(request.url)
            address=u.path+('?' +u.query if u.query else '')
            try:
                if closing or u.netloc!='uji':await route.abort();return
                headers=await request.all_headers()
                phase='data' if headers.get('x-portal-navigasi')=='1' else 'html'
                if request.method!='GET':control.posts.append(address)
                if u.path.startswith('/pelanggan'):
                    control.seen.append(dict(address=address,phase=phase,method=request.method,
                        portal_header=headers.get('x-portal-navigasi'),fetch_mode=headers.get('sec-fetch-mode'),fetch_dest=headers.get('sec-fetch-dest')))
                job=asyncio.create_task(c.request(request.method,address,content=request.post_data_buffer,
                    headers={k:v for k,v in headers.items() if k not in {'host','cookie','content-length'}}))
                jobs.add(job)
                response=await asyncio.wait_for(asyncio.shield(job),60)
                key=(address,phase);gate=control.gates.pop(key,None)
                if gate:gate.entered.set();await gate.release.wait()
                status,body=response.status_code,response.content
                if key in control.fail_once:
                    control.fail_once.remove(key)
                    # Availability negative AFTER genuine native auth/read;
                    # never replace a 401/403/404 with an artificial success.
                    assert status==200 and request.method=='GET' and phase=='data'
                    status,body=503,b'Synthetic owner read temporarily unavailable'
                await route.fulfill(status=status,body=body,headers={k:v for k,v in response.headers.items()
                    if k.lower() not in {'content-length','content-encoding','transfer-encoding','set-cookie'}})
            except BrowserError as error:
                if not(closing or gate or request.failure):control.errors.append(str(error));raise
            finally:
                if job:jobs.discard(job)
                if gate:gate.done.set()
                callbacks.discard(owner)
        await context.route('**/*',route)
        try:yield page,control
        finally:
            closing=True
            for hold in control.holds:hold.release.set()
            if callbacks:await asyncio.wait_for(asyncio.gather(*list(callbacks),return_exceptions=True),65)
            if jobs:await asyncio.wait_for(asyncio.gather(*list(jobs),return_exceptions=True),65)
            await context.close();await browser.close()

async def menu_click(page,path,width):
    if width<=900:await page.locator('#menu-pelanggan').click()
    await page.locator('.portal-sidebar nav a[href="'+path+'"]').click()

async def stable_paint(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

async def screenshot(page,name):
    folder=os.environ.get('DETAIL_OUT')
    if folder:await page.screenshot(path=str(Path(folder)/(name+'.png')),full_page=True)

@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('selected',[0,1])
async def test_seven_real_menu_clicks_before_html_and_data_are_customer_scoped(pg,portal,width,selected):
    foreign=('Rahasia Pelanggan B','LOT-RAHASIA-B','Kabar rahasia B','Rahasia seluruh pabrik') if selected==0 else ('Pemilik Portal A','LOT-QC-DETAIL','Hasil milik A','Rahasia seluruh pabrik')
    async with client(portal.accounts[selected]) as c:
        async with portal_browser(c,width) as (page,control):
            await page.goto(BASE+'/pelanggan/kabar',wait_until='load')
            await page.wait_for_function('()=>window.PadiKerangkaPortalUI&&document.getElementById("padi-portal-kerangka")')
            before=await _sidik(pg)
            for path,title in MENU:
                # Hold both potential target phases. An adopted menu must
                # not need HTML at all; its actual data GET is held separately.
                html=control.hold(path,'html');data=control.hold(path,'data')
                try:
                    await menu_click(page,path,width)
                    await asyncio.wait_for(data.entered.wait(),20)
                    frame=page.locator('[data-portal-native-frame]')
                    await expect(frame).to_be_visible();await expect(frame.locator('h1')).to_have_text(title)
                    await expect(frame).to_have_attribute('data-portal-address',path)
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    assert not html.entered.is_set(),'First click unexpectedly requested target HTML'
                    assert control.count(path,'html')==0
                    seen=[r for r in control.seen if r['address']==path and r['phase']=='data']
                    assert seen and seen[-1]['portal_header']=='1'
                    schema=aset()['schemas'][path.removeprefix('/pelanggan')]
                    for label,columns in schema['tables'].items():
                        table=frame.locator('section[aria-label="'+label+'"] table')
                        await expect(table.locator('thead th')).to_have_text(columns)
                        await expect(table.locator('tbody tr')).to_have_count(1)
                    for name in PAGES[path.removeprefix('/pelanggan')]['filters']:
                        await expect(frame.locator('[name="'+name+'"]').first).to_be_visible()
                    assert not await frame.locator('form[method=post],[name=_csrf],[data-post],[data-kirim]').count()
                    body=await page.locator('#isi-pelanggan').inner_text();assert all(value not in body for value in foreign)
                    if selected==0:await screenshot(page,'portal-framework-'+path.rsplit('/',1)[-1]+'-'+str(width))
                    data.release.set();await asyncio.wait_for(data.done.wait(),20)
                    await expect(frame).to_have_count(0)
                    await expect(page.locator('#isi-pelanggan h1')).to_have_text(title)
                    body=await page.locator('#isi-pelanggan').inner_text();assert all(value not in body for value in foreign)
                finally:
                    html.release.set();data.release.set();control.gates.pop((path,'html'),None)
            assert not control.posts and not control.errors,dict(posts=control.posts,errors=control.errors)
            assert await _sidik(pg)==before

@pytest.mark.parametrize('width',[390,1280])
async def test_error_retry_dirty_filter_stale_response_and_back_are_read_only(pg,portal,width):
    path='/pelanggan/laporan'
    async with client(portal.accounts[0]) as c:
        async with portal_browser(c,width) as (page,control):
            await page.goto(BASE+'/pelanggan/kabar',wait_until='load')
            before=await _sidik(pg)
            control.fail_once.add((path,'data'))
            await menu_click(page,path,width)
            frame=page.locator('[data-portal-native-frame]')
            await expect(frame.locator('[data-portal-read-retry]')).to_be_visible()
            await expect(frame.locator('select[name=jenis]')).to_be_visible()
            await expect(page.locator('.halaman-memuat')).to_have_count(0)
            assert control.count(path,'data')==1
            retry=control.hold(path,'data')
            try:
                await frame.locator('[data-portal-read-retry]').press('Enter')
                await asyncio.wait_for(retry.entered.wait(),20)
                await expect(frame).to_be_visible();await expect(frame.locator('[data-portal-read-retry]')).to_be_hidden()
                retry.release.set();await expect(frame).to_have_count(0)
            finally:retry.release.set()
            await menu_click(page,'/pelanggan/barang-masuk',width)
            await expect(page.locator('[data-portal-native-frame]')).to_have_count(0)
            hold=control.hold(path,'data')
            try:
                await menu_click(page,path,width);await asyncio.wait_for(hold.entered.wait(),20)
                await frame.locator('input[name=q]').fill('NO-MATCH-OWNER-FIXTURE')
                hold.release.set();await asyncio.wait_for(hold.done.wait(),20)
                await expect(frame.locator('[data-portal-read-status]')).to_contain_text('Pilihan pencarian berubah')
                await expect(frame.locator('input[name=q]')).to_have_value('NO-MATCH-OWNER-FIXTURE')
                await frame.locator('input[name=q]').press('Enter')
                await expect(frame).to_have_count(0)
                await expect(page.locator('#isi-pelanggan .pelanggan-catatan-kosong')).to_contain_text('Tidak ada hasil yang cocok')
                assert 'q=NO-MATCH-OWNER-FIXTURE' in page.url
            finally:hold.release.set()
            stale=control.hold('/pelanggan/barang-masuk','data')
            try:
                await menu_click(page,'/pelanggan/barang-masuk',width);await asyncio.wait_for(stale.entered.wait(),20)
                await menu_click(page,'/pelanggan/jasa-saya',width)
                await expect(page.locator('[data-portal-native-frame]')).to_have_count(0)
                await expect(page.locator('#isi-pelanggan h1')).to_have_text('Proses berjalan')
                stale.release.set();await asyncio.wait_for(stale.done.wait(),20);await stable_paint(page)
                await expect(page.locator('#isi-pelanggan h1')).to_have_text('Proses berjalan')
                assert page.url==BASE+'/pelanggan/jasa-saya'
            finally:stale.release.set()
            back=control.hold('/pelanggan/barang-masuk','data')
            try:
                await page.go_back(wait_until='commit')
                await asyncio.wait_for(back.entered.wait(),20)
                await expect(frame.locator('h1')).to_have_text('Barang masuk')
                back.release.set();await expect(frame).to_have_count(0)
                assert page.url==BASE+'/pelanggan/barang-masuk'
            finally:back.release.set()
            assert not control.posts and not control.errors,dict(posts=control.posts,errors=control.errors)
            assert await _sidik(pg)==before

async def test_document_negotiation_data_header_and_existing_customer_boundaries(pg,portal):
    async with client(portal.accounts[0]) as c:
        await c.get('/pelanggan/kabar',headers=DATA)
        before=await _sidik(pg)
        for path,title in MENU:
            document=await c.get(path,headers=DOC)
            assert document.status_code==200 and 'no-store' in document.headers['cache-control']
            soup=BeautifulSoup(document.text,'html.parser');frame=soup.select_one('[data-portal-native-frame]')
            assert frame and frame.h1.get_text()==title
            assert not frame.select('form[method=post],[name=_csrf],[data-post]')
            # Explicit protocol test, not fabricated browser Sec-Fetch proof.
            data=await c.get(path,headers={**DOC,**DATA})
            assert data.status_code==200 and not BeautifulSoup(data.text,'html.parser').select('[data-portal-native-frame]')
        assert (await c.get('/pelanggan/riwayat-giling/'+str(portal.process[1]['giling']))).status_code==404
        assert (await c.get('/pelanggan/barang-masuk?pelanggan_id='+str(portal.owners[1].id))).status_code==404
        assert await _sidik(pg)==before
    async with client(portal.accounts[1]) as c:
        assert (await c.get('/pelanggan/riwayat-giling/'+str(portal.process[0]['giling']))).status_code==404
    async with client(portal.accounts[2]) as c:
        before=await _sidik(pg)
        for path in ('/pelanggan/laporan','/pelanggan/riwayat-proses'):
            response=await c.get(path,headers=DATA)
            soup=BeautifulSoup(response.text,'html.parser')
            assert response.status_code==200 and 'Belum ada catatan' in soup.main.get_text()
            assert not soup.select('.pelanggan-catatan-baris')
        assert await _sidik(pg)==before
