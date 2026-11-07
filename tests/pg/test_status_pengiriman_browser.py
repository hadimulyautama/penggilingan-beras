from pathlib import Path
import pytest
from sqlalchemy import select
from app.models import ActivityLog
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_verifikasi_pengiriman import _setup,_body,_save
from tests.pg.test_riwayat_sosoh_desain_browser import browser
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('width',[1440,390])
async def test_selesai_timbang_belum_verifikasi_lalu_verifikasi_manual_asli(pg,gudang,width):
 from playwright.async_api import expect
 rs,tid=await _setup(pg,gudang,5);rid=rs[0].rec.id;before=await _stok(pg,gudang)
 async with await _klien(pg,gudang['adm'],'status-kirim') as c:
  async with browser(c,width) as page:
   await page.goto(f'/barang-keluar/{rid}')
   panel=page.locator('[data-status-timbang-pengiriman]')
   await expect(panel).to_contain_text('Selesai timbang');await expect(panel).to_contain_text('Menunggu verifikasi pengiriman')
   await page.screenshot(path=str(Path('..')/f'padi-pengiriman-{width}.png'),full_page=True)
   await page.goto(f'/verifikasi-pengiriman?perintah={rid}')
   await expect(page.locator('.sp-status')).to_contain_text('Selesai timbang')
   # Same real manual verification, with the existing review and save buttons.
   button=page.get_by_role('button',name='Periksa verifikasi manual',exact=True)
   if not await button.count():
    await page.get_by_role('button',name='Periksa kiriman',exact=True).first.click()
   await page.get_by_role('button',name='Periksa verifikasi manual',exact=True).click()
   await page.get_by_role('button',name='Verifikasi seluruh kiriman',exact=True).click()
   await expect(page.locator('.sp-status dd').last).to_have_text('Pengiriman terverifikasi')
   await page.goto(f'/barang-keluar/{rid}')
   await expect(page.locator('[data-status-timbang-pengiriman]')).to_contain_text('Pengiriman terverifikasi')
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
 assert await _stok(pg,gudang)==before
