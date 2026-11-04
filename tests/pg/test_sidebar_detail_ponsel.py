"""Sentuhan ponsel: sidebar, detail, dan data terlambat tanpa menutup menu pengguna."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
import pytest
from playwright.async_api import async_playwright,expect
from tests.pg.test_portal_pelanggan import portal,qc,client
from tests.pg.test_riwayat_giling import _klien
from hmu_identitas.peran import SUPERADMIN
from hmu_tampilan import VERSI

pytestmark=pytest.mark.asyncio
BASE='http://127.0.0.1:59994'

@pytest.mark.parametrize('pelanggan',[False,True])
@pytest.mark.parametrize('engine',os.environ.get('UJI_PONSEL_ENGINES','chromium').split(','))
@pytest.mark.parametrize('width',[int(v) for v in os.environ.get('UJI_PONSEL_WIDTHS','320,390').split(',')])
async def test_sidebar_detail_sekali_sentuh(pg,portal,pelanggan,engine,width):
    asal='/pelanggan/' if pelanggan else '/barang-masuk'
    daftar='/pelanggan/riwayat-proses' if pelanggan else '/jasa'
    detail=f'/pelanggan/riwayat-giling/{portal.process[0]["giling"]}' if pelanggan else f'/jasa/pelanggan/{portal.owners[0].id}'
    menu='.portal-sidebar' if pelanggan else '#laci'
    buka='.portal-menu-bawah' if pelanggan else '#buka-laci'
    tutup='.portal-tutup-menu' if pelanggan else '#laci .pd-close'
    c=client(portal.accounts[0]) if pelanggan else await _klien(pg,peran=SUPERADMIN)
    gates={p:asyncio.Event() for p in (daftar,detail)};started={p:asyncio.Event() for p in gates}
    async with c:
        pages={path:await c.get(path) for path in (asal,daftar)}
        links=BeautifulSoup(pages[daftar].text,'html.parser').select('main a[href]')
        detailHref=next(a['href'] for a in links if urlsplit(a['href']).path==detail)
        pages[detailHref]=await c.get(detailHref)
        assert all(r.status_code==200 for r in pages.values()),[(p,r.status_code) for p,r in pages.items()]
        async with async_playwright() as pw:
            browser=await getattr(pw,engine).launch()
            profile=pw.devices['iPhone SE' if width<=375 else 'iPhone 13'] if engine=='webkit' else {}
            ctx=await browser.new_context(**{**profile,'viewport':{'width':width,'height':844},'is_mobile':True,'has_touch':True,'device_scale_factor':2,'service_workers':'block','reduced_motion':'reduce'})
            await ctx.add_cookies([{'name':x.name,'value':x.value,'url':BASE} for x in c.cookies.jar])
            writes=[];errors=[];refresh=[False]
            async def app(route):
                req=route.request;u=urlsplit(req.url)
                if not req.url.startswith(BASE+'/'):return await route.abort()
                if req.method!='GET':writes.append(u.path);return await route.abort()
                if u.path=='/api/aliran':return await route.fulfill(status=204,body='')
                if u.path=='/api/keadaan':return await route.fulfill(json={'n':'uji','versi':VERSI})
                if u.path in gates:
                    started[u.path].set()
                    try:await asyncio.wait_for(gates[u.path].wait(),15)
                    except TimeoutError:return await route.abort()
                response=pages.get(u.path+('?' + u.query if u.query else ''))
                if response is None:response=await c.get(u.path+('?' + u.query if u.query else ''))
                body=response.content
                if refresh[0] and u.path==daftar:body=body.replace(b'</main>',b'<p data-uji-pembaruan>Data terbaru uji</p></main>')
                await route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding')},body=body)
            await ctx.route('**/*',app)
            page=await ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            await page.add_init_script("""document.addEventListener('click',e=>{let a=e.target.closest('a[href]');if(a){window.taps=window.taps||{};window.taps[a.pathname]=(window.taps[a.pathname]||0)+1;window.lastTap=performance.now();}},true);new MutationObserver(()=>{if(document.querySelector('.halaman-memuat'))requestAnimationFrame(()=>window.shellMs=performance.now()-window.lastTap)}).observe(document,{childList:true,subtree:true});""")
            try:
                await page.goto(BASE+asal)
                await page.locator(buka).tap()
                await page.locator(menu+f' a[href="{daftar}"]').first.tap()
                await asyncio.wait_for(started[daftar].wait(),5)
                await expect(page.locator('.halaman-memuat')).to_be_visible(timeout=700)
                await expect(page).to_have_url(BASE+daftar)
                # Membuka menu lagi ketika data masih di jalan adalah tindakan
                # pengguna; datangnya data tidak boleh menutup atau menggantinya.
                await page.locator(buka).tap()
                await expect(page.locator(menu)).to_be_visible()
                await asyncio.sleep(2);gates[daftar].set()
                await asyncio.sleep(.4)
                await expect(page.locator(menu)).to_be_in_viewport(ratio=.5,timeout=700)
                await page.locator(tutup).tap()
                await expect(page.locator('.halaman-memuat')).to_have_count(0,timeout=10000)
                # Respons pembaruan tiba ketika pengguna sedang mengetik filter.
                # Isian, simpul yang sedang dipakai, dan guliran harus bertahan.
                gates[daftar].clear();started[daftar].clear();refresh[0]=True
                if pelanggan:await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                else:await page.evaluate('PINDAH.muatPerubahan()')
                await asyncio.wait_for(started[daftar].wait(),5)
                field=page.locator('main input[type=search]').first
                await field.fill('ketikan belum dikirim')
                await field.evaluate('(el)=>window.inputAsli=el')
                top=await page.evaluate("() => {window.readScroller=[document.querySelector('main'),document.scrollingElement].find(el=>el && el.scrollHeight>el.clientHeight+40);if(!window.readScroller)return 0;window.readScroller.scrollTop=40;return window.readScroller.scrollTop}")
                assert top>0, 'Halaman uji harus benar-benar dapat digulir'
                await asyncio.sleep(2);gates[daftar].set();await asyncio.sleep(.4)
                await expect(field).to_have_value('ketikan belum dikirim')
                assert await page.evaluate('window.inputAsli.isConnected')
                assert await page.evaluate('window.readScroller.scrollTop')==top
                await field.fill('');await field.evaluate('(el)=>el.blur()')
                await expect(page.locator('main a[href="'+detailHref+'"]').first).to_be_visible()
                await page.locator('main a[href="'+detailHref+'"]').first.tap()
                await asyncio.wait_for(started[detail].wait(),5)
                await expect(page.locator('.halaman-memuat')).to_be_visible(timeout=700)
                await expect(page).to_have_url(BASE+detailHref)
                await asyncio.sleep(2);gates[detail].set()
                await expect(page.locator('.halaman-memuat')).to_have_count(0,timeout=10000)
                taps=await page.evaluate('window.taps')
                assert taps[daftar]==taps[detail]==1,taps
                assert not errors,errors
                assert not writes,writes
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if pelanggan:assert 'Rahasia Pelanggan B' not in await page.locator('main').inner_text()
                out=Path(os.environ.get('UJI_PONSEL_OUT','output/ponsel'));out.mkdir(parents=True,exist_ok=True)
                name=('portal' if pelanggan else 'padiflow')+f'-{engine}-{width}'
                await page.screenshot(path=str(out/(name+'.png')))
                (out/(name+'.json')).write_text(json.dumps({'engine':engine,'width':width,'touch':True,'sidebar_taps':taps[daftar],'detail_taps':taps[detail],'data_delay_ms':2000,'menu_preserved':True,'input_preserved':True,'scroll_preserved':True,'scroll_test_top':top,'errors':errors,'writes':writes})+'\n')
                await page.go_back();await expect(page).to_have_url(BASE+daftar)
                await expect(page.locator('.halaman-memuat')).to_have_count(0,timeout=10000)
            finally:
                for gate in gates.values():gate.set()
                await ctx.close();await browser.close()
