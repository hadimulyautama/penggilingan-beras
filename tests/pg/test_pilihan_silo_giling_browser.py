"""Daftar line/silo tetap bekerja meski respons jaringan datang bergantian."""
import asyncio
import os
from urllib.parse import urlsplit
import httpx
import pytest
from tests.pg.test_giling_beberapa_silo import silos
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pengeringan_desain_browser import browser
from app.services.seed import seed_master
from tests.pg.test_form_pindah_silo import fakta

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('UJI_BROWSER_PILIHAN_SILO') != '1', reason='Browser silo lokal opsional')]


@pytest.mark.parametrize('lambat', ['line', 'silo'])
@pytest.mark.parametrize('width', [390, 1440])
async def test_silo_termuat_meski_line_otomatis_datang_lebih_dulu(pg, silos, lambat, width):
    from playwright.async_api import expect
    await seed_master()
    async with await _klien(pg, peran='superadmin') as c:
        original = c.request
        async def request(method, url, **kw):
            r = await original(method, url, **kw)
            path = urlsplit(str(url)).path
            if (lambat == 'line' and path == '/api/actions/lini-produksi'
                    or lambat == 'silo' and path == '/api/actions/silo-siap-giling'):
                await asyncio.sleep(.3)
            return r
        c.request = request
        async with browser(c, width) as page:
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            await page.locator('#f_lini_id').wait_for(state='visible')
            try:
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2, timeout=3000)
            except AssertionError:
                pytest.fail(str(errors)+' | '+await page.locator('#b_silo').inner_text())
            await page.locator('#b_silo input[value=A]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('10.000', timeout=3000)


@pytest.mark.parametrize('gangguan', ['sementara', 'respons_lama'])
async def test_pulih_daftar_dan_respons_lama_tidak_menghapus_pilihan(pg, silos, gangguan):
    from playwright.async_api import expect
    await seed_master()
    before = await fakta(pg)
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        original = c.request
        failed = False
        async def request(method, url, **kw):
            nonlocal failed
            path = urlsplit(str(url))
            if path.path == '/api/actions/silo-siap-giling':
                if gangguan == 'sementara' and 'lini_id=' in path.query and not failed:
                    failed = True
                    return httpx.Response(503, json={'detail':'Daftar sedang diperbarui.'})
                if gangguan == 'respons_lama' and not path.query:
                    await asyncio.sleep(.5)
                    return httpx.Response(503, json={'detail':'Respons lama gagal.'})
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            if gangguan == 'sementara':
                retry = page.get_by_role('button', name='Muat ulang pilihan silo', exact=True)
                await expect(retry).to_be_visible()
                line = await page.locator('#f_lini_id').input_value()
                await page.locator('#simpan').click()
                await retry.click()
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
                assert await page.locator('#f_lini_id').input_value() == line
            else:
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
                await page.locator('#b_silo input[value=A]').check()
                await page.wait_for_timeout(700)
                await expect(page.locator('#b_silo input[value=A]')).to_be_checked()
                assert 'Respons lama gagal' not in await page.locator('#b_silo').inner_text()
            assert await fakta(pg) == before


async def test_operator_memulai_giling_setelah_daftar_line_dan_silo_siap(pg, silos):
    from playwright.async_api import expect
    from sqlalchemy import select, func
    from app.models import MillingProcess, MillingProcessSource
    await seed_master()
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
            await page.locator('#b_silo input[value=B]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('6.000')
            await page.locator('#simpan').click()
            await expect(page.locator('#lembar')).to_be_hidden()
    async with pg() as db:
        proc = await db.scalar(select(MillingProcess))
        assert proc.berat_gabah_masuk_kg == 6000
        assert await db.scalar(select(func.count()).select_from(MillingProcess)) == 1
        assert await db.scalar(select(func.count()).select_from(MillingProcessSource)) == 1
