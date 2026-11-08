"""Pengemasan beras tetap dapat disimpan dari formulir dengan API dan DB asli."""
import pytest
from sqlalchemy import select,func
from app.models import FinishedGoodsStock
from tests.pg.test_form_pengemasan_beras import packing,sosoh
from tests.pg.test_barang_keluar import _klien
from tests.pg.test_pengeringan_desain_browser import browser

@pytest.mark.parametrize('width',[390,1440])
async def test_packing_beras_tetap_berjalan(pg,packing,width):
    from playwright.async_api import expect
    async with await _klien(pg,packing['user'],'uji-packing-beras-browser',mode='admin') as c:
        async with browser(c,width) as page:
            await page.emulate_media(reduced_motion='reduce')
            await page.goto('https://uji/stok-produk/detail?jenis=medium&gudang=g2&buka=catat_packing')
            await page.locator('#f_sumber').wait_for(state='visible')
            await page.locator('#f_sumber option[value="'+packing['sumber']+'"]').wait_for(state='attached')
            await page.locator('#f_sumber').select_option(packing['sumber'])
            await page.locator('#f_kemasan option[value="laminasi|25"]').wait_for(state='attached')
            await page.locator('#f_kemasan').select_option('laminasi|25')
            await page.locator('#f_jumlah_karung').fill('10')
            await expect(page.locator('#pk-preview')).to_contain_text('250 kg')
            await page.locator('#simpan').click()
            await page.locator('#lembar').wait_for(state='hidden')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
    async with pg() as db:
        assert await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)))==850
