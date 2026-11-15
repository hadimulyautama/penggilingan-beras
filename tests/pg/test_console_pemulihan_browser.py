"""Pemilik memulihkan akun melalui HTTP asli; hanya PostgreSQL loopback uji."""
import os,asyncio
import pytest
from sqlalchemy import select
from hmu_core import KeanggotaanPerusahaan,AksesProdukAnggota,Perusahaan
from hmu_identitas.model import Akun
from hmu_identitas.sandi import cek_sandi
from app.config import settings
from app.services import console_bantuan as help
from tests.pg.test_console_monitoring import orang,action,ALLOWED
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_console_website_integrasi import api_http
from tests.pg.test_pengaturan_organisasi import fakta

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi,pytest.mark.skipif(os.getenv('UJI_BROWSER_ORGANISASI')!='1',reason='Profil browser Console eksplisit')]

@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('lost_reply',[False,True])
async def test_koneksi_putus_periksa_dan_simpan_tidak_menghilangkan_cap_atau_isian(pg,orang,monkeypatch,width,lost_reply):
    from playwright.async_api import async_playwright,expect
    x=orang;monkeypatch.setattr(settings,'teraflow_web_url','https://tf.uji')
    async with pg() as db:(await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True;await db.commit()
    result,_=await action(pg,x,'tautan_sandi');before=await fakta(pg)
    state=dict(check=0,save=0);urls=[];first_checked=asyncio.Event()
    async with api_http() as base,async_playwright() as pw:
        browser=await getattr(pw,os.environ.get('UJI_BROWSER','chromium')).launch()
        try:
            # Fault injection harus melewati router Playwright, bukan service worker.
            context=await browser.new_context(viewport=dict(width=width,height=900),service_workers='block');page=await context.new_page();page.on('request',lambda r:urls.append(r.url))
            if lost_reply:await page.add_init_script("const timer=window.setTimeout;let first=true;window.setTimeout=(fn,ms)=>{if(ms===15000&&first){first=false;ms=2000;}return timer(fn,ms);};")
            async def verify(route):
                state['check']+=1
                if state['check']==1:
                    if lost_reply:await asyncio.sleep(3)
                    try:await route.fulfill(status=503,content_type='text/html',body='<h1>Sementara offline</h1>')
                    except Exception:
                        if not lost_reply:raise
                    first_checked.set()
                else:await route.continue_()
            async def save(route):
                state['save']+=1
                if state['save']==1:
                    if lost_reply:
                        response=await route.fetch();assert response.status==200
                    await route.fulfill(status=502,content_type='text/html',body='<h1>Gateway sementara gagal</h1>')
                else:await route.continue_()
            await page.route('**/pemulihan/periksa',verify);await page.route('**/pemulihan/simpan',save)
            await page.goto(base+'/pemulihan#cap='+result['cap']+'&produk=teraflow')
            retry=page.locator('[data-retry-pemulihan]');await expect(retry).to_be_visible();assert await page.evaluate('location.hash')==''
            await asyncio.wait_for(first_checked.wait(),timeout=5)
            await retry.click();form=page.locator('[data-form-pemulihan]');await expect(form).to_be_visible();await expect(page.locator('[data-identitas]')).to_contain_text('TeraFlow')
            await expect(page.locator('[data-dampak-bersama]')).to_be_visible()
            for field in ('sandi','ulangi'):await form.locator('[name='+field+']').fill('sandi-baru-console-123')
            await form.locator('button').click();await expect(page.locator('[data-pesan]')).to_contain_text('coba lagi')
            await expect(form.locator('[name=sandi]')).to_have_value('sandi-baru-console-123');await expect(form.locator('button')).to_be_enabled()
            await form.locator('button').click()
            if lost_reply:
                await expect(page.locator('[data-pesan]')).to_contain_text('Tautan pemulihan tidak valid')
                await expect(page.locator('[data-pesan]')).to_contain_text('sandi yang Anda kirim sebelumnya')
                await expect(form).to_be_visible()
            else:
                await expect(page.locator('[data-pesan]')).to_contain_text('Kata sandi diperbarui')
                await expect(page.locator('[data-masuk]')).to_have_attribute('href','https://tf.uji/timbangan/masuk')
                await expect(form).to_be_hidden()
            assert state==dict(check=2,save=2)
            assert all(result['cap'] not in url for url in urls)
            assert result['cap'] not in await page.evaluate('JSON.stringify({local:localStorage,session:sessionStorage})')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await context.close()
        finally:await browser.close()
    async with pg() as db:
        account=await db.get(Akun,x['aid']);assert account.token_version==2 and cek_sandi('sandi-baru-console-123',account.password_hash)
        assert (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif
    after=await fakta(pg);assert {k:v for k,v in before.items() if k not in ALLOWED}=={k:v for k,v in after.items() if k not in ALLOWED}
