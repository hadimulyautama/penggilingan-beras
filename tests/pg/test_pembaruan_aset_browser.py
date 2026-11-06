"""Pembaruan kode otomatis; draf tetap utuh sampai pengguna selesai."""
import os
from urllib.parse import urlsplit
import httpx
import pytest
from tests.pg.test_giling_beberapa_silo import silos
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pengeringan_desain_browser import browser
from tests.pg.test_form_pindah_silo import fakta
from app.services.seed import seed_master

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('UJI_BROWSER_PEMBARUAN') != '1', reason='Browser pembaruan lokal opsional')]


@pytest.mark.parametrize('draft', [False, True])
async def test_pembaruan_dipasang_otomatis_pada_saat_aman(pg, silos, draft):
    from playwright.async_api import expect
    await seed_master()
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        original = c.request
        tawarkan = False
        async def request(method, url, **kw):
            nonlocal tawarkan
            r = await original(method, url, **kw)
            if urlsplit(str(url)).path == '/api/keadaan' and tawarkan:
                tawarkan = False
                data = r.json();data['versi'] = 'rilis-uji-baru';data['n'] += '.rilis-uji-baru'
                return httpx.Response(200, json=data)
            return r
        c.request = request
        async with browser(c, 390) as page:
            await page.route('**/api/aliran', lambda r:r.abort())
            navigasi = []
            page.on('framenavigated', lambda f:navigasi.append(f.url) if f == page.main_frame else None)
            await page.goto('https://uji/pekerjaan'+('?buka=mulai_giling' if draft else '?tab=tindakan'))
            if draft:
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
                await page.locator('#b_silo input[value=A]').check()
                await expect(page.locator('#mg-bobot')).to_contain_text('10.000')
            before = await fakta(pg)
            jumlah = len(navigasi)
            tawarkan = True
            await page.evaluate('PINDAH.diam()')
            if draft:
                await expect(page.locator('.pil-versi')).to_contain_text('setelah isian selesai')
                await page.wait_for_timeout(1200)
                assert len(navigasi) == jumlah
                await expect(page.locator('#b_silo input[value=A]')).to_be_checked()
                assert await fakta(pg) == before
                await page.locator('#lembar').get_by_role('button', name='Batal', exact=True).click()
                await page.get_by_role('button', name='Buang & tutup', exact=True).click()
            await page.wait_for_function('() => performance.getEntriesByType("navigation")[0]?.type === "reload"', timeout=5000)
            await page.wait_for_load_state('networkidle')
            assert len(navigasi) > jumlah
            assert await fakta(pg) == before


async def test_dokumen_lama_menerima_pembaruan_tanpa_ketukan(pg, silos):
    from hmu_tampilan import CAP_ASET
    await seed_master()
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        original = c.request
        pertama = True
        async def request(method, url, **kw):
            nonlocal pertama
            r = await original(method, url, **kw)
            if pertama and urlsplit(str(url)).path == '/pekerjaan':
                pertama = False
                html = r.text.replace('data-versi="'+CAP_ASET+'"', 'data-versi="533"', 1)
                return httpx.Response(200, headers=r.headers, content=html.encode(), request=r.request)
            return r
        c.request = request
        before = await fakta(pg)
        async with browser(c, 390) as page:
            await page.route('**/api/aliran', lambda r:r.abort())
            await page.goto('https://uji/pekerjaan?tab=tindakan')
            await page.wait_for_function('() => performance.getEntriesByType("navigation")[0]?.type === "reload"', timeout=5000)
            await page.wait_for_load_state('networkidle')
            assert await page.locator('html').get_attribute('data-versi') == CAP_ASET
            assert await fakta(pg) == before


async def test_identitas_rilis_menggerakkan_penanda_tanpa_transaksi(pg, silos, monkeypatch):
    import hmu_tampilan
    from app.web.api import _baca_penanda
    await seed_master()
    before = await fakta(pg)
    a = await _baca_penanda()
    monkeypatch.setattr(hmu_tampilan, 'CAP_ASET', hmu_tampilan.CAP_ASET+'-rilis-lain')
    b = await _baca_penanda()
    assert a['n'] != b['n'] and a['versi'] != b['versi']
    assert a['versi_aplikasi'] == b['versi_aplikasi']
    assert await fakta(pg) == before
