"""Klik native: frame terbit sebelum semua respons tujuan, tanpa POST bisnis."""
import asyncio
import json
import os
from pathlib import Path

import pytest
import httpx
from playwright.async_api import expect

from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE

pytestmark = pytest.mark.asyncio


async def pintu(page, href, width):
    if width < 900:
        await page.locator('#buka-laci').click()
    link = page.locator('#laci a[href="'+href+'"]')
    await expect(link).to_be_visible()
    return link


async def siap(page, jenis):
    await expect(page.locator('.halaman-memuat')).to_have_count(0)
    if jenis == 'barang-masuk':
        await expect(page.locator('[data-bm-page]:not([data-bm-shell])')).to_be_visible()
    else:
        await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
        await expect(page.locator('nav[aria-label="Tab pekerjaan"]')).to_be_visible()


async def kerangka_instans(page, t, reads, trigger, alamat, jenis, kolom, width, gambar, gagal=False):
    path = alamat.split('?')[0]
    api = '/api/halaman-bertahap/' + jenis
    html_enter, html_release = asyncio.Event(), asyncio.Event()
    enter, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    t['gates'][path] = (html_enter, html_release)
    t['gates'][api] = (enter, release)
    t['completed'][api] = done
    before = len(reads)
    try:
        await trigger()
        await asyncio.wait_for(enter.wait(), 15)
        await expect(page).to_have_url(BASE + alamat)
        assert not html_enter.is_set(), 'Tujuan adopted tidak boleh meminta HTML foreground'
        assert not any(r['url'].split('?')[0] == path for r in reads[before:])
        await expect(page.locator('.halaman-memuat')).to_have_count(0)
        await expect(page.locator('.bingkai')).to_have_attribute('data-pindah-alamat', alamat)
        await expect(page.locator('#padi-kerangka-langsung')).to_have_count(1)
        await expect(page.locator('thead th')).to_have_count(kolom)
        await expect(page.locator('input[name=cari]:visible')).to_be_enabled()
        await expect(page.locator('nav[aria-label="'+('Bagian Barang Masuk' if jenis=='barang-masuk' else 'Tab pekerjaan')+'"] a')).to_have_count(3)
        if jenis == 'barang-masuk':
            await expect(page.locator('section[aria-label="Barang Masuk"]')).to_be_visible()
            await expect(page.locator('[data-bm-results]')).to_have_attribute('aria-busy','true')
        else:
            # Ini heading helper native yang sama, bukan label klik Berjalan0.
            await expect(page.get_by_role('heading', name='Pekerjaan', exact=True)).to_be_visible()
            await expect(page.locator('[data-shell-table-wrap]')).to_have_attribute('aria-busy','true')
        if width < 900:
            await page.locator('#buka-laci').click()
            await expect(page.locator('#laci')).to_be_visible()
            await page.keyboard.press('Escape')
            await expect(page.locator('#laci')).to_be_hidden()
        else:
            handle = page.get_by_role('separator', name='Ubah lebar sidebar')
            await handle.focus()
            old = await page.evaluate('parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar"))||280')
            await handle.press('ArrowRight')
            new = await page.evaluate('parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar"))')
            assert new == old + 16
            await handle.press('ArrowLeft')
        if os.environ.get('PHASE_OUT'):
            engine=os.environ.get('OWNER_BROWSER','chromium')
            await page.screenshot(path=str(Path(os.environ['PHASE_OUT'])/(engine+'-'+gambar+'.png')), full_page=True)
        release.set()
        await asyncio.wait_for(done.wait(),15)
        if gagal:
            await expect(page.locator('[data-shell-message]')).to_contain_text('Gagal memuat data; ini bukan daftar kosong')
            await expect(page.locator('thead th')).to_have_count(kolom)
            await expect(page.locator('[data-shell-table-wrap]')).to_have_attribute('aria-busy','false')
            await page.locator('[data-shell-retry]').click()
        await siap(page, jenis)
        assert not any(r['url'].split('?')[0] == path for r in reads[before:])
    finally:
        html_release.set();release.set()
        t['gates'].pop(path,None)
        t['gates'].pop(api,None)


@pytest.mark.parametrize('role', ['operator','admin'])
@pytest.mark.parametrize('width', [390,1280])
async def test_empat_literal_native_sebelum_semua_response(pg,lengkap,role,width):
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as c:
        before=await _sidik(pg)
        reads=[];native=c.request;fault=dict(next=False)
        async def request(method,url,**kw):
            reads.append(dict(method=method,url=str(url),headers={k:v for k,v in kw.get('headers',{}).items() if k.lower() in {'x-pindah','x-kerangka-halaman','x-barang-masuk-cari','sec-fetch-mode','sec-fetch-dest'}}))
            assert method=='GET', 'Frame/navigation tidak boleh mengirim POST'
            result=await native(method,url,**kw)
            if fault['next'] and str(url).split('?')[0]=='/api/halaman-bertahap/pekerjaan':
                fault['next']=False
                return httpx.Response(503,json={'detail':'Fixture pembaca belum tersedia'})
            return result
        c.request=request
        async with peramban(c,width) as (page,t):
            await page.add_init_script("""window.__riwayatPush=[];const push=history.pushState;history.pushState=function(...a){window.__riwayatPush.push(a[2]);return push.apply(this,a);};""")
            await page.goto(BASE+'/kabar')
            link=await pintu(page,'/barang-masuk',width)
            old=await page.evaluate('history.length')
            await kerangka_instans(page,t,reads,lambda:link.click(),'/barang-masuk','barang-masuk',6,width,'instant-BM-'+role+'-'+str(width))
            assert await page.evaluate('history.length') == old+1
            assert await page.evaluate('window.__riwayatPush.filter(x=>x==="/barang-masuk").length') == 1
            # Tab lokal tetap controller BM native. Back dari Kabar-lah yang
            # membuktikan dua literal status melalui provider SDK, bukan POST.
            for status, columns in [('diterima',7),('belum',6)]:
                oldroot=await page.locator('[data-bm-page]').element_handle()
                entered,released,completed=asyncio.Event(),asyncio.Event(),asyncio.Event()
                t['gates']['/barang-masuk']=(entered,released)
                t['completed']['/barang-masuk']=completed
                awal=len(reads);pushes=await page.evaluate('window.__riwayatPush.length')
                try:
                    await page.locator('nav[aria-label="Bagian Barang Masuk"] a[href*="status='+status+'"]').click()
                    await asyncio.wait_for(entered.wait(),15)
                    await expect(page.locator('[data-bm-results] th')).to_have_count(columns)
                    await expect(page.locator('nav[aria-label="Bagian Barang Masuk"] a[href*="status='+status+'"]')).to_have_attribute('aria-current','page')
                    await expect(page.locator('.bm-jumlah')).to_contain_text('Jumlah hasil belum tersedia')
                    await expect(page.locator('[data-bm-results]')).to_have_attribute('aria-busy','true')
                    actual=[r for r in reads[awal:] if r['url'].split('?')[0]=='/barang-masuk']
                    assert len(actual)==1 and actual[0]['headers'].get('x-barang-masuk-cari')=='1'
                    assert await page.evaluate('n=>window.__riwayatPush.slice(n)',pushes)==['/barang-masuk?status='+status]
                    await expect(page).to_have_url(BASE+'/barang-masuk?status='+status)
                    released.set();await asyncio.wait_for(completed.wait(),15)
                    await page.wait_for_function('n=>!n.isConnected',arg=oldroot)
                finally:
                    released.set();t['gates'].pop('/barang-masuk',None)
                alamat='/barang-masuk?status='+status
                await expect(page).to_have_url(BASE+alamat)
                await (await pintu(page,'/kabar',width)).click()
                await expect(page).to_have_url(BASE+'/kabar')
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                length=await page.evaluate('history.length')
                pushes=await page.evaluate('window.__riwayatPush.length')
                await kerangka_instans(page,t,reads,lambda:page.go_back(),alamat,'barang-masuk',columns,width,'instant-Back-'+status+'-'+role+'-'+str(width))
                assert await page.evaluate('history.length') == length
                assert await page.evaluate('window.__riwayatPush.length') == pushes
            await (await pintu(page,'/pekerjaan',width)).click()
            await expect(page).to_have_url(BASE+'/pekerjaan')
            await expect(page.locator('nav[aria-label="Tab pekerjaan"]')).to_be_visible()
            link=page.locator('nav[aria-label="Tab pekerjaan"] a[href="/pekerjaan?tab=berjalan"]')
            fault['next']=role=='operator' and width==390
            await kerangka_instans(page,t,reads,lambda:link.click(),'/pekerjaan?tab=berjalan','pekerjaan',5,width,'instant-Berjalan-'+role+'-'+str(width),gagal=fault['next'])
            assert not t['posts'] and not t['errors'],t['errors']
            assert await _sidik(pg)==before
            if os.environ.get('PHASE_OUT'):
                engine=os.environ.get('OWNER_BROWSER','chromium')
                (Path(os.environ['PHASE_OUT'])/(engine+'-four-literal-'+role+'-'+str(width)+'.json')).write_text(json.dumps(dict(role=role,width=width,requests=reads,foreground_adopted_HTML=0,history_once=True,Back_no_push=True,native_Escape_resize=True,all_public_tables_unchanged=True,business_POSTs=0),indent=2)+'\n')
