"""Kerangka harus terlihat ketika respons data sengaja masih ditahan."""
import asyncio
import json
import os
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright, expect, Error as BrowserError
from tests.pg.test_portal_pelanggan import portal, qc, client
from tests.pg.test_riwayat_giling import _klien
from hmu_identitas.peran import SUPERADMIN

pytestmark=pytest.mark.asyncio
BASE='http://127.0.0.1:59996'


def portal_native_columns(html):
    """Require actual receipt headers and both filters; an empty shell fails."""
    native=BeautifulSoup(html,'html.parser')
    columns=[n.get_text(' ',strip=True) for n in native.select('.masuk-kepala > span')]
    assert len(columns)==7 and columns[0]=='Nama / tiket'
    assert not native.select_one('[data-portal-native-frame]'), 'Golden must be the complete native read, not its pending framework'
    assert native.select_one('form.pelanggan-filter-masuk[method=get] select[name=jenis]')
    assert native.select_one('form.pelanggan-filter-masuk[method=get] input[name=cari]')
    return columns


async def test_portal_native_oracle_rejects_missing_columns_or_filter_controls():
    # Pure negative controls for the source oracle, not a served response,
    # permission, business row or a replacement for the native fixture GET.
    html='<div class="masuk-kepala"><span>Nama / tiket</span>'+''.join('<span>Kolom</span>' for _ in range(6))+'</div><form class="pelanggan-filter-masuk" method="get"><select name="jenis"></select><input name="cari"></form>'
    assert len(portal_native_columns(html))==7
    for selector in ('.masuk-kepala','select[name=jenis]','input[name=cari]'):
        doc=BeautifulSoup(html,'html.parser');doc.select_one(selector).decompose()
        with pytest.raises(AssertionError):portal_native_columns(str(doc))
    with pytest.raises(AssertionError):portal_native_columns('<div data-portal-native-frame>'+html+'</div>')

async def _tuntaskan_baca(reads,pending):
    hasil=await asyncio.wait_for(asyncio.gather(*reads,return_exceptions=True),20) if reads else []
    assert not pending,'Seluruh request baca ASGI harus selesai sebelum fixture dilepas'
    # Seluruh job sudah terminal sebelum kegagalan pertama diteruskan. Jangan
    # meninggalkan job kedua ketika job pertama gagal atau dibatalkan.
    for nilai in hasil:
        if isinstance(nilai,BaseException):raise nilai


@pytest.mark.parametrize('batal',[False,True])
async def test_cleanup_menunggu_semua_baca_sebelum_meneruskan_error(batal):
    loop=asyncio.get_running_loop();gagal=loop.create_future();lambat=loop.create_future()
    pending={gagal,lambat}
    for job in pending:job.add_done_callback(pending.discard)
    selesai=asyncio.create_task(_tuntaskan_baca([gagal,lambat],pending))
    async def giliran():
        batas=loop.create_future();loop.call_soon(batas.set_result,None);await batas
    try:
        await giliran()
        if batal:gagal.cancel()
        else:gagal.set_exception(ValueError('Galat baca sintetis'))
        # Barrier event-loop, bukan jeda jaringan/waktu yang ditebak.
        for _ in range(4):await giliran()
        assert not selesai.done(),'Error pertama tidak boleh melepas job lain yang masih berjalan'
        lambat.set_result('baca selesai')
        with pytest.raises(asyncio.CancelledError if batal else ValueError):
            await selesai
        assert not pending
    finally:
        if not lambat.done():lambat.set_result('cleanup kontrol')
        await asyncio.gather(selesai,return_exceptions=True)


@pytest.mark.parametrize('pelanggan',[False,True])
@pytest.mark.parametrize('width',[390,1440])
async def test_ui_datang_sebelum_respons_data(pg,portal,pelanggan,width):
    await asyncio.wait_for(jalankan(pg,portal,pelanggan,width),45)

async def jalankan(pg,portal,pelanggan,width):
    c=client(portal.accounts[0]) if pelanggan else await _klien(pg,peran=SUPERADMIN)
    asal='/pelanggan/' if pelanggan else '/barang-masuk'
    tujuan='/pelanggan/barang-masuk' if pelanggan else '/stok'
    gate=asyncio.Event();started=asyncio.Event();writes=[];stock_html=[]
    pending=set();reads=[];closing=False
    async def baca(path,headers):
        # Penutupan browser tidak otomatis menunggu request ASGI in-process.
        # Pisahkan pekerjaan baca agar callback yang dibatalkan tidak meninggalkan
        # transaksi/session sebelum fixture berikutnya melakukan TRUNCATE.
        job=asyncio.create_task(c.get(path,headers=headers))
        pending.add(job);reads.append(job);job.add_done_callback(pending.discard)
        return await asyncio.shield(job)
    async with c:
        # HTML dan pemeriksaan akses tetap berasal dari aplikasi/PG asli.
        # Ambil sebelum browser agar simulasi jaringan tidak menahan sesi DB.
        pages={path:await c.get(path) for path in (asal,tujuan)}
        assert all(r.status_code==200 for r in pages.values())
        # Native fixture response is the golden structure; no generic loading
        # page or fabricated receipt DTO may satisfy the portal assertion.
        portal_columns=[]
        if pelanggan:
            native_target=await c.get(tujuan,headers={'X-Portal-Navigasi':'1'})
            assert native_target.status_code==200
            portal_columns=portal_native_columns(native_target.text)
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            ctx=await browser.new_context(viewport={'width':width,'height':840},service_workers='block')
            await ctx.add_cookies([{'name':x.name,'value':x.value,'url':BASE} for x in c.cookies.jar])
            try:
                async def app(route):
                    req=route.request;u=urlsplit(req.url)
                    if closing:
                        try:await route.abort()
                        except BrowserError:pass
                        return
                    if not req.url.startswith(BASE+'/'):await route.abort();return
                    if req.method!='GET':writes.append(u.path);await route.abort();return
                    if u.path=='/api/aliran':await route.fulfill(status=204,body='');return
                    if u.path=='/api/keadaan':await route.fulfill(json={'n':'uji','versi':'493'});return
                    if not pelanggan and u.path==tujuan:stock_html.append(u.path)
                    if u.path==(tujuan if pelanggan else '/api/halaman-bertahap/stok'):
                        started.set();await asyncio.wait_for(gate.wait(),12)
                    response=pages.get(u.path) if not u.query else None
                    if response is None:response=await baca(u.path+('?' + u.query if u.query else ''),headers={k:v for k,v in req.headers.items() if k.lower() in ('x-pindah','x-portal-navigasi','accept')})
                    try:
                        await route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding')},body=response.content)
                    except BrowserError:
                        if not closing:raise
                await ctx.route('**/*',app)
                page=await ctx.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto(BASE+asal)
                if width<900:
                    await page.locator('.portal-menu-bawah' if pelanggan else '#buka-laci').click()
                await page.evaluate("""portal => {window.clickAt=0;const selector=portal?'[data-portal-native-frame][data-portal-page="/barang-masuk"]':'[data-halaman-bertahap][data-kind="stok"]';document.addEventListener('click',()=>{window.clickAt=performance.now()},true);new MutationObserver(()=>{if(document.querySelector(selector) && !window.shellMs)requestAnimationFrame(()=>{window.shellMs=performance.now()-window.clickAt})}).observe(document.body,{childList:true,subtree:true});}""",pelanggan)
                menu='.portal-sidebar' if pelanggan else '#laci'
                await page.locator(menu+' a[href="'+tujuan+'"]').first.click()
                await asyncio.wait_for(started.wait(),5)
                if pelanggan:
                    root=page.locator('[data-portal-native-frame][data-portal-page="/barang-masuk"]')
                    await expect(root).to_be_visible(timeout=700)
                    await expect(root).to_have_attribute('data-portal-address',tujuan)
                    await expect(root).to_have_attribute('aria-busy','true')
                    await expect(root.locator('.pelanggan-sapaan h1')).to_have_text('Barang masuk')
                    await expect(root.locator('form[role=search] select[name=jenis]')).to_be_visible()
                    await expect(root.locator('form[role=search] input[name=cari]')).to_be_visible()
                    assert await root.locator('.masuk-kepala > span').all_text_contents()==portal_columns
                    await expect(root.locator('[data-portal-placeholder]')).to_be_visible()
                    await expect(root.locator('[data-portal-read-status]')).to_have_attribute('role','status')
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                else:
                    root=page.locator('[data-halaman-bertahap][data-kind="stok"]')
                    await expect(root).to_be_visible(timeout=700)
                    await expect(root.locator('h1,.halaman-bertahap__kepala')).to_have_count(0)
                    await expect(root.locator('nav[aria-label="Jenis stok"]')).to_be_visible()
                    await expect(root.locator('.kontrol-pencarian>[data-sk-buka="sk-filter"]')).to_be_visible()
                    assert await root.locator('th[scope="col"]').count()>=6
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    assert not stock_html,'Kerangka spesifik harus ada tanpa meminta HTML tujuan'
                await expect(page).to_have_url(BASE+tujuan)
                await expect(page.locator(menu+' a[href="'+tujuan+'"]')).to_have_attribute('aria-current','page')
                assert not gate.is_set()
                await page.wait_for_timeout(2000)
                elapsed=await page.evaluate('window.shellMs')
                assert elapsed is not None and elapsed<500,elapsed
                out=Path(os.environ.get('UJI_KERANGKA_OUT','output/kerangka'))
                out.mkdir(parents=True,exist_ok=True)
                name=('portal' if pelanggan else 'padiflow')+'-'+str(width)
                await page.screenshot(path=str(out/(name+'.png')))
                gate.set()
                await expect(page.locator('.halaman-memuat')).to_have_count(0,timeout=15000)
                if not pelanggan:
                    await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0,timeout=15000)
                    await expect(page.locator('[data-stok-controls]')).to_be_visible()
                assert not writes,writes
                assert not errors,errors
                if pelanggan:
                    await expect(page.locator('[data-portal-native-frame]')).to_have_count(0,timeout=15000)
                    assert await page.locator('.masuk-kepala > span').all_text_contents()==portal_columns
                    assert 'Rahasia Pelanggan B' not in await page.locator('main').inner_text()
                (out/(name+'.json')).write_text(json.dumps({'shell_ms':elapsed,'held_response_ms':2000,'width':width,'writes':writes,'errors':errors})+'\n')
                # Kembali memulihkan halaman asal, bukan membuat entri riwayat ganda.
                await page.go_back()
                await expect(page).to_have_url(BASE+asal)
                await expect(page.locator('.halaman-memuat')).to_have_count(0,timeout=15000)
            finally:
                closing=True;gate.set()
                try:
                    try:
                        await ctx.close()
                    finally:
                        # Simpan juga job yang sudah selesai: SQL/app error tidak
                        # boleh hilang hanya karena callback browser sudah tutup.
                        await _tuntaskan_baca(reads,pending)
                finally:
                    await browser.close()
