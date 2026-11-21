"""Operator normal melihat dua bobot terpisah, atau isian tetap saat saldo berubah."""
import os
from pathlib import Path
import pytest
from playwright.async_api import expect
from app.models import User
from tests.pg.test_broken_silo_persiapan_atomik import spill,foto,sosoh,pesan
from tests.pg.test_broken_silo_saldo_bebas import sidik
from tests.pg.test_barang_keluar import _klien
from tests.pg.test_pengeringan_desain_browser import browser

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('mode',['save','changed'])
async def test_operator_persiapan_terpisah_dan_saldo_berubah(pg,spill,width,mode):
    async with pg() as db:
        user=await db.get(User,spill['user']);user.role='operator';await db.commit()
    async with await _klien(pg,spill['user'],'broken-prep-browser',mode='operator') as c:
        async with browser(c,width) as page:
            await page.goto('https://uji/stok-produk/detail?jenis=broken&gudang=g2&buka=masukkan_broken_silo')
            await page.locator('#f_proses option[value="pemilik|pabrik"]').wait_for(state='attached')
            await page.locator('#f_proses').select_option('pemilik|pabrik')
            await page.locator('#f_silo option[value="C"]').wait_for(state='attached')
            await page.locator('#f_silo').select_option('C')
            await page.locator('#f_berat_kg').fill('1350')
            await expect(page.locator('#bk-stock')).to_contain_text('1.900 kg')
            section=page.locator('.bk-preparation')
            await expect(section).to_be_visible()
            await expect(section).to_contain_text('350 kg')
            await expect(section).to_contain_text('1.700 kg')
            await expect(section).to_contain_text('tidak masuk silo')
            await expect(section).to_contain_text('POL-UJIB-01')
            await expect(section).to_contain_text('POL-BF-2150')
            before=await sidik(pg)
            out=Path(os.environ['PHASE_OUT'])
            await page.screenshot(path=str(out/f'preview-operator-{mode}-{width}.png'),full_page=True)
            await section.scroll_into_view_if_needed()
            await page.screenshot(path=str(out/f'preparation-operator-{mode}-{width}.png'),full_page=True)
            assert await sidik(pg)==before
            if mode=='changed':
                await pesan(pg,spill,1000)
                before=await sidik(pg)
            await page.locator('#simpan').focus();await page.keyboard.press('Enter')
            if mode=='save':
                await page.locator('#lembar').wait_for(state='hidden')
            else:
                await expect(page.locator('.formulir-gagal')).to_contain_text('Transaksi ini tidak tersimpan')
                await expect(page.locator('#bk-stock')).to_contain_text('900 kg')
                await expect(page.locator('#f_berat_kg')).to_have_value('1350')
                await expect(page.locator('#f_silo')).to_have_value('C')
                await expect(page.locator('#f_proses')).to_have_value('pemilik|pabrik')
                await expect(page.locator('#f_proses option:checked')).not_to_contain_text('1.900')
                await page.locator('#f_berat_kg').focus();await expect(page.locator('#f_berat_kg')).to_be_focused()
                await page.screenshot(path=str(out/f'changed-operator-{width}.png'),full_page=True)
                assert await sidik(pg)==before
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')


async def test_operator_sumber_ditahan_ada_langkah_admin_tanpa_saldo_nol(pg,spill):
    from tests.pg.test_masukkan_broken_silo import _kemas
    await _kemas(pg,spill,jumlah_karung=1)
    await _kemas(pg,{**spill,'kode_pol':'POL-BF-2150'},jumlah_karung=40)
    async with pg() as db:
        user=await db.get(User,spill['user']);user.role='operator';await db.commit()
    async with await _klien(pg,spill['user'],'broken-prep-held-browser',mode='operator') as c:
        before=await sidik(pg)
        async with browser(c,390) as page:
            await page.goto('https://uji/stok-produk/detail?jenis=broken&gudang=g2&buka=masukkan_broken_silo')
            option=page.locator('#f_proses option[value="pemilik|pabrik"]')
            await expect(option).to_be_disabled()
            await expect(page.locator('#simpan')).to_be_disabled()
            await expect(page.locator('#bk-stock')).to_contain_text('Admin perlu meninjau')
            await expect(page.locator('#bk-stock')).to_contain_text('saldo tidak dianggap nol')
            await expect(page.locator('#bk-preview')).to_contain_text('tidak ada pembukuan')
            await page.locator('#f_berat_kg').fill('1350')
            await expect(page.locator('#f_berat_kg')).to_have_value('1350')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await page.screenshot(path=str(Path(os.environ['PHASE_OUT'])/'held-operator-390.png'),full_page=True)
            assert await sidik(pg)==before
