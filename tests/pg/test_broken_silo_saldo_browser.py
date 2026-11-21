"""Formulir native: saldo berubah, isian tetap utuh, tanpa kiriman ulang otomatis."""
import os
from pathlib import Path
import pytest
from app.models import User
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_broken_silo_saldo_bebas import foto,sosoh,sidik
from tests.pg.test_barang_keluar import _klien
from tests.pg.test_pengeringan_desain_browser import browser

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,width',[('operator',390),('operator',1280),('superadmin',390),('superadmin',1280)])
async def test_saldo_terbaru_isian_utuh_dan_keyboard(pg,foto,role,width):
    from playwright.async_api import expect
    async with pg() as db:
        user=await db.get(User,foto['user']);user.role=role;await db.commit()
    async with await _klien(pg,foto['user'],'broken-form-'+role,mode='operator' if role=='operator' else 'admin') as c:
        async with browser(c,width) as page:
            posts=[]
            async def native_post(route):
                req=route.request;posts.append(req.post_data_json)
                headers={k:v for k,v in req.headers.items() if k.lower() not in ('host','cookie','content-length')}
                response=await c.request(req.method,req.url,headers=headers,content=req.post_data_buffer)
                assert response.status_code==400,response.text
                await route.fulfill(status=response.status_code,body=response.content,headers={'content-type':'application/json'})
            await page.route('**/api/actions/masukkan-broken-silo',native_post)
            await page.goto('https://uji/stok-produk/detail?jenis=broken&gudang=g2&buka=masukkan_broken_silo')
            await page.locator('#f_proses option[value="pemilik|pabrik"]').wait_for(state='attached')
            await page.locator('#f_proses').select_option('pemilik|pabrik')
            await page.locator('#f_silo option[value="C"]').wait_for(state='attached')
            await page.locator('#f_silo').select_option('C')
            await page.locator('#f_berat_kg').fill('1350')
            await expect(page.locator('#bk-stock')).to_contain_text('2.900')
            await expect(page.locator('#bk-preview')).to_contain_text('1.350')
            await expect(page.locator('#bk-stock')).to_contain_text('0 karung')
            # Transaksi sintetis lain yang sah memakai saldo setelah preview.
            async with pg() as db:
                await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,foto['user']),jasa_id=None,nama_silo='D',berat_kg=2000)
            before=await sidik(pg)
            await page.locator('#simpan').focus();await page.keyboard.press('Enter')
            error=page.locator('.formulir-gagal')
            await expect(error).to_contain_text('Transaksi ini tidak tersimpan')
            await expect(error).not_to_contain_text('belum berhasil sepenuhnya')
            await expect(error).not_to_contain_text('Kosongkan')
            await expect(page.locator('#bk-stock')).to_contain_text('900 kg')
            await expect(page.locator('#f_proses option:checked')).to_contain_text('900 kg dapat dipakai')
            await expect(page.locator('#f_proses option:checked')).not_to_contain_text('2.900')
            await expect(page.locator('#bk-preview')).to_contain_text('tidak cukup')
            await expect(page.locator('#f_berat_kg')).to_have_value('1350')
            await expect(page.locator('#f_silo')).to_have_value('C')
            await expect(page.locator('#f_proses')).to_have_value('pemilik|pabrik')
            assert len(posts)==1 # Refresh saldo bukan POST atau retry otomatis.
            assert await sidik(pg)==before
            await page.locator('#f_berat_kg').focus();await expect(page.locator('#f_berat_kg')).to_be_focused()
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            out=Path(os.environ.get('PHASE_OUT', 'bukti/broken-silo'));out.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(out/f'form-{role}-{width}.png'),full_page=True)
