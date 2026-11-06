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
from tests.pg.test_dryer_gudang_kerja import tempat as dryer_satu, batch as buat_batch

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
            await page.locator('#f_lini_id').wait_for(state='attached')
            try:
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2, timeout=3000)
            except AssertionError:
                pytest.fail(str(errors)+' | '+await page.locator('#b_silo').inner_text())
            await page.locator('#b_silo input[value=A]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('10.000', timeout=3000)
            await expect(page.locator('#f_lini_id')).to_be_hidden()
            await expect(page.locator('#alat_otomatis_lini_id')).to_contain_text('Penggilingan 1')


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
                await expect(page.locator('#b_silo')).to_contain_text('dipulihkan otomatis')
                line = await page.locator('#f_lini_id').input_value()
                await page.locator('#simpan').click()
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
                assert await page.locator('#f_lini_id').input_value() == line
                assert await page.get_by_role('button', name='Muat ulang pilihan silo', exact=True).count() == 0
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


@pytest.mark.parametrize('keadaan', ['ditutup', 'offline'])
async def test_retry_otomatis_berhenti_saat_tidak_aktif_dan_lanjut_saat_online(pg, silos, keadaan):
    from playwright.async_api import expect
    await seed_master()
    before = await fakta(pg)
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        original = c.request
        requests = 0
        pulih = False
        async def request(method, url, **kw):
            nonlocal requests
            p = urlsplit(str(url))
            if p.path == '/api/actions/silo-siap-giling' and 'lini_id=' in p.query:
                requests += 1
                if not pulih:
                    return httpx.Response(503, json={'detail':'Gangguan sementara uji.'})
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            await expect(page.locator('#b_silo')).to_contain_text('dipulihkan otomatis')
            if keadaan == 'ditutup':
                await page.locator('#lembar').get_by_role('button', name='Batal', exact=True).click()
                await expect(page.locator('#lembar')).to_be_hidden()
            else:
                await page.context.set_offline(True)
            jumlah = requests
            await page.wait_for_timeout(1300)
            assert requests == jumlah
            if keadaan == 'offline':
                pulih = True
                await page.context.set_offline(False)
                await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
                assert requests > jumlah
            assert await fakta(pg) == before


async def test_lebih_dari_satu_line_tetap_dipilih_operator(pg, silos):
    from playwright.async_api import expect
    from tests.pg.test_giling_beberapa_silo import _line_kedua
    await seed_master()
    kedua = await _line_kedua(pg, silos)
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            await expect(page.locator('#f_lini_id option')).to_have_count(3)
            await expect(page.locator('#f_lini_id')).to_be_visible()
            assert await page.locator('#f_lini_id').input_value() == ''
            await page.locator('#f_lini_id').select_option(str(kedua))
            await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
            await page.locator('#b_silo input[value=A]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('10.000')


async def test_dryer_tunggal_ditetapkan_otomatis_tanpa_memulai_proses(pg, dryer_satu):
    from playwright.async_api import expect
    from sqlalchemy import select, func
    from app.models import User, PurchaseBatch, DryingLot
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        async with pg() as db:
            uid = await db.scalar(select(User.id).order_by(User.id.desc()).limit(1))
        bid = await buat_batch(pg, dryer_satu, uid)
        async with pg() as db:
            b = await db.get(PurchaseBatch, bid)
            b.status_batch = 'di_dryer';b.dryer_id = dryer_satu['dryer']
            await db.commit()
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_pengeringan')
            await expect(page.locator('#f_dryer_id')).to_have_value(str(dryer_satu['dryer']))
            await expect(page.locator('#f_dryer_id')).to_be_hidden()
            await expect(page.locator('#alat_otomatis_dryer_id')).to_contain_text('ditetapkan otomatis')
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(DryingLot)) == 0
