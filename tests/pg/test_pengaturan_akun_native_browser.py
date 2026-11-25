"""Account structure before native read; no account/profile transaction."""
import asyncio
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE

pytestmark=pytest.mark.asyncio
DOC={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
async def test_account_renderer_keeps_native_form_and_post_result_paths(pg,stok_lengkap,role,warehouse):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        shell=await client.get('/pengaturan/akun',headers=DOC)
        assert shell.status_code==200
        pending=BeautifulSoup(shell.text,'html.parser').select_one('[data-pengaturan-akun-kerangka]')
        assert pending and pending.select_one('input').has_attr('disabled')
        assert not pending.select('input[name],form[action],form[method],input[type=password]')
        for path in ('/pengaturan/akun','/pengaturan/akun?pesan=nama','/pengaturan/akun?err=nama'):
            response=await client.get(path,headers={'X-Pindah':'1'})
            assert response.status_code==200
            doc=BeautifulSoup(response.text,'html.parser')
            assert not doc.select('[data-pengaturan-akun-kerangka]')
            assert doc.select_one('form[method=post][action="/pengaturan/nama"] input[name=nama]')
            assert doc.select_one('input[name=_csrf]')
        assert await _sidik(pg)==before

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
@pytest.mark.parametrize('width',[390,1280])
async def test_account_first_click_keeps_fields_before_native_data(pg,stok_lengkap,role,warehouse,width):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/pengaturan',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaUI&&document.getElementById('padi-kerangka-ui')")
            entered,release=asyncio.Event(),asyncio.Event();t['gates']['/pengaturan/akun']=(entered,release)
            requests=[];page.on('request',lambda r:requests.append((r.method,r.resource_type,r.url)))
            try:
                await page.locator('.pg-pintu[href="/pengaturan/akun"]').click()
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-pengaturan-akun-kerangka]');await expect(root).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await expect(root.locator('h1')).to_have_text('Nama & kata sandi')
                await expect(root.locator('input')).to_be_disabled()
                await expect(root.get_by_role('button',name='Simpan nama')).to_be_disabled()
                field=await root.locator('input').bounding_box();password=await root.locator('a.tindakan').bounding_box()
                assert not any(kind=='document' and u==BASE+'/pengaturan/akun' for _,kind,u in requests)
                release.set()
                await expect(root).to_have_count(0)
                await expect(page.locator('input[name=nama]')).to_be_enabled()
                await expect(page.locator('form[action="/pengaturan/nama"] input[name=_csrf]')).to_have_count(1)
                final=await page.locator('input[name=nama]').bounding_box()
                final_password=await page.locator('a.tindakan[href^="/ganti-sandi"]').bounding_box()
                assert all(abs(field[k]-final[k])<=2 and abs(password[k]-final_password[k])<=2 for k in ('x','y','width','height')),(field,final,password,final_password)
                assert not t['posts'] and not t['errors']
            finally:release.set()
        assert await _sidik(pg)==before
