"""Owner first-click native process detail tests; no transaction is sent."""
import asyncio
import os
from pathlib import Path
import pytest
from playwright.async_api import expect
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_halaman_bertahap import _sidik
pytestmark=pytest.mark.asyncio

async def shot(page,name):
    folder=os.environ.get('DETAIL_OUT')
    if folder:await page.screenshot(path=str(Path(folder)/(name+'.png')),full_page=True)

@pytest.mark.parametrize('role',['admin','operator'])
@pytest.mark.parametrize('width',[390,1280])
async def test_sosoh_current_native_work_link_has_layout_before_get(pg,running,role,width):
    _,code,_,_=running
    path='/proses-aktif/sosoh/'+code
    async with await _klien(pg,peran=role,gudang='Gudang 2') as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/pekerjaan?tab=berjalan',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaSosohUI&&document.querySelector('[data-sosoh-native-catalog]')&&document.querySelector('#padi-sosoh-kerangka')")
            row=page.locator('.proses-aktif-list__row[data-proses=sosoh]').filter(has_text=code)
            link=row.locator('a.proses-aktif-list__detail').first
            entered,release=asyncio.Event(),asyncio.Event();t['gates'][path]=(entered,release)
            try:
                await link.press('Enter')
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-sosoh-native-html]');await expect(root).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert await root.locator('input:not(:disabled),button[data-save-output]:not(:disabled)').count()==0
                await expect(root.locator('[data-sn-results]')).to_have_count(1)
                assert await root.locator('table thead th').count()>0
                await shot(page,'sosoh-native-'+role+'-'+str(width))
                release.set();await expect(root).to_have_count(0)
                await expect(page.locator('[data-sosoh-ringkas]')).to_be_visible()
                assert not t['posts'] and not t['errors'],t
            finally:release.set()
        assert await _sidik(pg)==before

@pytest.mark.parametrize('role',['admin','operator'])
@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('phase',['pengeringan','pendinginan'])
async def test_dryer_phase_current_link_tabs_and_abandoned_get(pg,pengeringan,role,width,phase):
    if phase=='pendinginan':
        from app.models import User
        from app.penggilingan.gudang1.services import drying
        async with pg() as db:
            user=await db.get(User,pengeringan['user'])
            await drying.finish_drying(db,user=user,kode_lot=pengeringan['kode'],kadar_air_akhir=13)
    code=pengeringan['kode'];path='/proses-aktif/'+phase+'/'+code
    async with await _klien(pg,peran=role,gudang='Gudang 1') as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/pekerjaan?tab=berjalan',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaPengeringanUI&&document.querySelector('[data-pengeringan-native-catalog]')")
            link=page.locator('.proses-aktif-list__row[data-proses='+phase+']').filter(has_text=code).locator('a.proses-aktif-list__detail').first
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event();t['gates'][path]=(entered,release);t['completed'][path]=done
            try:
                await link.click();await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-dryer-native-html]');await expect(root).to_be_visible()
                await expect(root).to_have_attribute('data-fase',phase)
                await expect(root.locator('[role=tab]')).to_have_count(4)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await root.locator('[data-dryer-tab=bahan]').focus();await page.keyboard.press('ArrowRight')
                await expect(root.locator('[data-dryer-panel=pengukuran]')).to_be_visible()
                assert await root.locator('table thead th').count()>0
                await shot(page,'dryer-native-'+phase+'-'+role+'-'+str(width))
                # Native sidebar must remain usable while data is held.
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/barang-masuk"]').click()
                await expect(page).to_have_url(BASE+'/barang-masuk')
                release.set();await asyncio.wait_for(done.wait(),20)
                await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                await expect(page.locator('[data-dryer-native-html],.pengeringan-detail')).to_have_count(0)
                assert not t['posts'] and not t['errors'],t
            finally:release.set()
        assert await _sidik(pg)==before
