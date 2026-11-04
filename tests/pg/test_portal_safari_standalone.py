"""Cookie portal di WebKit: HTTPS, profil persisten, mandiri, dan restart.

Mode mandiri meniru navigator.standalone untuk jalur PWA aplikasi. Ini bukan
pemasangan aplikasi di iPhone fisik; datanya seluruhnya sintetis di DB uji.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx
import pytest
from playwright.async_api import async_playwright,expect,Error
from app.config import settings
from app.web.portal import security
from hmu_identitas import token
from tests.pg.test_portal_pelanggan import portal,qc

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('mandiri',[False,True],ids=['safari-biasa','ikon-layar-utama'])
async def test_sesi_webkit_persisten(pg,portal,tmp_path,monkeypatch,mandiri):
    url=pg.kw['bind'].url
    assert url.host in ('127.0.0.1','localhost') and url.database.startswith('uji_')
    root=Path(__file__).resolve().parents[2]
    out=Path(os.environ.get('UJI_SAFARI_OUT','output/safari'));out.mkdir(parents=True,exist_ok=True)
    name='standalone' if mandiri else 'safari'
    cert=tmp_path/'cert.pem';key=tmp_path/'key.pem'
    subprocess.run(['/opt/homebrew/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','2','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1,DNS:localhost'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'https://127.0.0.1:{port}'
    secret='safari-portal-synthetic-20261104'
    monkeypatch.setattr(settings,'secret_key',secret)
    env={**os.environ,'DATABASE_URL':url.render_as_string(hide_password=False),'SECRET_KEY':secret,'PERAN_PROSES':'web','KLEDO_API_KEY':'','ANTHROPIC_API_KEY':'','ADMIN_SANDI_AWAL':''}
    logfile=(out/(name+'-server.log')).open('w');process=None
    async def start():
        proc=await asyncio.create_subprocess_exec(sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--ssl-keyfile',str(key),'--ssl-certfile',str(cert),'--log-level','warning',cwd=root,env=env,stdout=logfile,stderr=logfile)
        async with httpx.AsyncClient(verify=False,trust_env=False,timeout=2) as c:
            for _ in range(100):
                if proc.returncode is not None:raise RuntimeError('Server HTTPS uji berhenti')
                try:
                    if (await c.get(base+'/health')).status_code==200:return proc
                except httpx.HTTPError:pass
                await asyncio.sleep(.1)
        proc.terminate();await proc.wait();raise TimeoutError('Server HTTPS uji belum siap')
    async def stop(proc):
        if proc and proc.returncode is None:
            proc.terminate()
            try:await asyncio.wait_for(proc.wait(),10)
            except TimeoutError:proc.kill();await proc.wait()
    process=await start();contexts=[];errors=[]
    try:
        async with async_playwright() as pw:
            async def buka():
                opts={**pw.devices['iPhone 13'],'viewport':{'width':390,'height':844},'ignore_https_errors':True,'service_workers':'allow','reduced_motion':'reduce'}
                opts.pop('default_browser_type',None)
                ctx=await pw.webkit.launch_persistent_context(str(tmp_path/'profile'),**opts)
                contexts.append(ctx)
                if mandiri:await ctx.add_init_script("Object.defineProperty(navigator,'standalone',{value:true,configurable:true})")
                page=ctx.pages[0] if ctx.pages else await ctx.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)))
                return ctx,page
            async def cookie(ctx):
                found=[x for x in await ctx.cookies(base+'/pelanggan/') if x['name']==security.COOKIE]
                assert len(found)==1,'Cookie sesi pelanggan harus tetap ada'
                return found[0]
            ctx,page=await buka()
            assert not [x for x in await ctx.cookies() if x['name']==security.COOKIE]
            await page.goto(base+'/pelanggan/masuk')
            await page.locator('[name=username]').fill(portal.accounts[0].username)
            await page.locator('[name=sandi]').fill('rahasia123')
            await page.locator('button[type=submit]').tap()
            await expect(page).to_have_url(base+'/pelanggan/')
            await expect(page.locator('main h1')).to_have_text('Beranda')
            first=await cookie(ctx)
            assert first['secure'] and first['httpOnly'] and first['sameSite']=='Lax'
            assert first['path']=='/pelanggan' and first['expires']-time.time()>29*86400
            assert security.COOKIE not in await page.evaluate('document.cookie')
            if mandiri:
                assert await page.evaluate('navigator.standalone===true')
                assert await page.locator('[data-pasang-area]').first.is_hidden()
            # Jalur worker sebenarnya dan manifest harus berada dalam scope portal.
            manifest=await ctx.request.get(base+'/pelanggan/manifest.webmanifest')
            meta=await manifest.json();assert meta['start_url']==meta['scope']=='/pelanggan/' and meta['display']=='standalone'
            await page.wait_for_function("navigator.serviceWorker.getRegistration('/pelanggan/').then(r=>!!r&&!!r.active)",timeout=10000)
            # Tutup proses browser, buka profil yang sama tanpa menyalin cookie.
            await ctx.close();contexts.remove(ctx)
            ctx,page=await buka();await page.goto(base+'/pelanggan/')
            await expect(page.locator('main h1')).to_have_text('Beranda')
            assert bool((await cookie(ctx))['value']==first['value'])
            # Sentuhan sidebar dan detail juga melalui HTTPS + worker aktif,
            # termasuk ketika cabang ikon layar utama dipakai aplikasi.
            await page.locator('.portal-menu-bawah').tap()
            await page.locator('.portal-sidebar a[href="/pelanggan/riwayat-proses"]').first.tap()
            await expect(page).to_have_url(base+'/pelanggan/riwayat-proses')
            detail_path=f'/pelanggan/riwayat-giling/{portal.process[0]["giling"]}'
            detail=page.locator(f'main a[href="{detail_path}"], main a[href^="{detail_path}?"]').first
            await expect(detail).to_be_visible()
            detail_href=await detail.get_attribute('href')
            await detail.tap()
            await expect(page).to_have_url(base+detail_href)
            await expect(page.locator('.halaman-memuat')).to_have_count(0)
            assert 'Rahasia Pelanggan B' not in await page.locator('main').inner_text()
            # Berpindah ke halaman/tab lain lalu kembali menjalankan jalur resume.
            cover=await ctx.new_page();await cover.goto('about:blank')
            hidden=await page.evaluate('document.hidden')
            await page.bring_to_front();await cover.close()
            await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            await page.goto(base+'/pelanggan/riwayat-proses')
            await expect(page.locator('main h1')).to_have_text('Riwayat proses')
            # Token lama masih sah; GET harus memperpanjangnya menjadi 30 hari.
            old=token.buat_token(security.key(),akun_id=portal.accounts[0].id,versi=portal.accounts[0].token_version,umur_detik=12*3600,ekstra={'pid':portal.accounts[0].pelanggan_id})
            replacement={k:first[k] for k in ['name','domain','path','httpOnly','secure','sameSite']}
            replacement.update(value=old,expires=time.time()+12*3600)
            await ctx.add_cookies([replacement]);await page.goto(base+'/pelanggan/barang-saya')
            renewed=await cookie(ctx)
            assert bool(renewed['value']!=old)
            assert renewed['expires']-time.time()>29*86400
            # Layanan web restart dengan kunci tetap tidak membuang sesi browser.
            await ctx.close();contexts.remove(ctx);await stop(process);process=await start()
            ctx,page=await buka();await page.goto(base+'/pelanggan/')
            await expect(page.locator('main h1')).to_have_text('Beranda')
            # Putus koneksi ke backend sebenarnya: worker harus menangani
            # fetch gagal, lalu sesi tetap sah setelah server tersedia lagi.
            await page.wait_for_function('!!navigator.serviceWorker.controller')
            await stop(process);process=None
            await page.goto(base+'/pelanggan/riwayat-proses?uji_luring=1')
            await expect(page.locator('main h1')).to_have_text('Tanpa jaringan')
            process=await start()
            await page.locator('a[href="/pelanggan/"]').tap()
            await expect(page.locator('main h1')).to_have_text('Beranda')
            assert (await cookie(ctx))['value']==renewed['value']
            # Keluar eksplisit tetap menghapus cookie dan memutus akses.
            await page.locator('.portal-menu-bawah').tap()
            await page.locator('.portal-pengaturan summary').tap()
            await page.locator('form[action="/pelanggan/keluar"] button').tap()
            await expect(page).to_have_url(base+'/pelanggan/masuk')
            assert not [x for x in await ctx.cookies() if x['name']==security.COOKIE]
            await page.goto(base+'/pelanggan/')
            await expect(page).to_have_url(base+'/pelanggan/masuk')
            assert not errors,errors
            await page.screenshot(path=str(out/(name+'-logout.png')))
            (out/(name+'.json')).write_text(json.dumps({'engine':'WebKit 26.0','iphone_profile':'iPhone 13','standalone_emulated':mandiri,'https':True,'http_only':True,'secure':True,'same_site':'Lax','cookie_path':'/pelanggan','lifetime_days':30,'browser_restart_preserved':True,'backend_restart_preserved':True,'renewal_preserved':True,'resume_event_preserved':True,'actual_tab_hidden_observed':hidden,'service_worker_active':True,'sidebar_and_detail_single_tap':True,'backend_unavailable_recovery_preserved':True,'explicit_logout_clears_cookie':True,'errors':errors},indent=2)+'\n')
    finally:
        # Playwright sudah menutup browser saat bloknya keluar karena assertion.
        # Cleanup tidak boleh menimpa kegagalan utama atau melewati stop server.
        for ctx in contexts:
            try:await ctx.close()
            except Error:pass
        await stop(process);logfile.close()
