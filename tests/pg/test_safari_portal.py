"""Portal pada mesin browser yang sama; semua data berasal dari PostgreSQL uji."""
import pytest
from playwright.async_api import expect
from tests.pg.test_portal_alur_hp import portal, alur, catatan, qc, transaksi
from tests.pg.test_portal_pelanggan import client
from tests.pg.test_portal_auto_update import fingerprint
from tests.pg.test_pengeringan_desain_browser import browser

pytestmark=pytest.mark.asyncio

async def test_portal_iphone_stok_proses_qc_tetap_scoped_dan_tanpa_mutasi(pg,portal,alur):
    before=await fingerprint(pg)
    async with client(portal.accounts[0]) as c:
        async with browser(c,390) as page:
            for name in ('beranda','stok_bahan','stok_produk','proses','qc_gabah','qc_pk'):
                await page.goto('https://uji'+alur[name])
                await expect(page.locator('main h1')).to_be_visible()
                assert 'Rahasia Pelanggan B' not in await page.locator('body').inner_text()
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'),name
                assert await page.locator('main [data-post],main [data-aksi]').count()==0
    assert await fingerprint(pg)==before
