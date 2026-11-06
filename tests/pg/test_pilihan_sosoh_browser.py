"""Reproduksi HP operator G2: alat dan silo pulih otomatis tanpa membuang formulir."""
import asyncio
import json
from tests.pg.test_giling_beberapa_silo import silos
import os
from urllib.parse import urlsplit
import httpx
import pytest
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pengeringan_desain_browser import browser
from tests.pg.test_form_mulai_penyosohan import fakta
from app.services.seed import seed_master

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('UJI_BROWSER_PILIHAN_SILO') != '1', reason='Browser lokal opsional')]


@pytest.mark.parametrize('peran', ['operator','admin','superadmin'])
@pytest.mark.parametrize('width', [390,1440])
async def test_tombol_kartu_silo_memulai_sosoh_dengan_alat_yang_benar(pg,gudang2,peran,width):
    from playwright.async_api import expect
    from sqlalchemy import select,func
    from app.models import PolishingProcess,PolishingSiloUsage
    await seed_master()
    async with await _klien(pg,peran=peran,gudang='Gudang 2') as c:
        async with browser(c,width) as page:
            await page.route('**/api/aliran',lambda r:r.abort())
            errors=[]
            page.on('response',lambda r:errors.append(r.status) if '/api/actions/' in r.url and r.status>=400 else None)
            await page.goto('https://uji/pekerjaan' if peran=='operator' else 'https://uji/')
            link=page.locator('a[href*="buka=mulai_penyosohan"][href*="nilai=B"]').first
            await link.wait_for(state='attached')
            if not await link.is_visible():
                await link.locator('xpath=ancestor::details[1]/summary').click()
            await link.click()
            await expect(page.locator('#alat_otomatis_lini_id')).to_contain_text('Penyosohan 1')
            assert (await page.locator('#f_lini_id').input_value()).isdigit()
            await expect(page.locator('#b_silo input[value=B]')).to_be_checked()
            await expect(page.locator('#mg-bobot')).to_contain_text('9.800')
            await page.locator('#simpan').click()
            await expect(page.locator('#lembar')).not_to_be_visible()
            assert not errors,errors
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PolishingProcess))==1
        usage=await db.scalar(select(PolishingSiloUsage))
        assert float(usage.berat_awal_kg)==9800


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('gangguan', ['alat', 'silo', 'alat_lambat'])
async def test_pilihan_g2_pulih_dan_alat_otomatis(pg, gudang2, width, gangguan):
    from playwright.async_api import expect
    await seed_master()
    before = await fakta(pg)
    async with await _klien(pg, peran='operator', gudang='Gudang 2') as c:
        original = c.request
        failed = False
        async def request(method, url, **kw):
            nonlocal failed
            path = urlsplit(str(url))
            if path.path == '/api/actions/lini-produksi' and 'penyosohan' in path.query:
                if gangguan == 'alat_lambat':
                    await asyncio.sleep(.3)
                if gangguan == 'alat' and not failed:
                    failed = True
                    return httpx.Response(503, json={'detail':'Gangguan sementara.'})
            if path.path == '/api/actions/silo-bahan-g2' and 'lini_id=' in path.query and gangguan == 'silo' and not failed:
                failed = True
                return httpx.Response(503, json={'detail':'Gangguan sementara.'})
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, width) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_penyosohan')
            await expect(page.locator('#alat_otomatis_lini_id')).to_contain_text('Penyosohan 1', timeout=5000)
            await expect(page.locator('#f_lini_id')).to_be_hidden()
            await expect(page.locator('#b_silo input[value=B]')).to_be_enabled(timeout=5000)
            await expect(page.locator('#galat_pilihan_lini_id')).to_have_count(0)
            await page.locator('#b_silo input[value=B]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('9.800')
            await expect(page.locator('#simpan')).to_be_enabled()
            assert await page.get_by_role('button', name='Muat ulang pilihan silo').count() == 0
            assert await fakta(pg) == before


@pytest.mark.parametrize('status', [401, 403])
async def test_penolakan_daftar_tidak_mengalihkan_atau_menghapus_form(pg, gudang2, status):
    from playwright.async_api import expect
    await seed_master()
    async with await _klien(pg, peran='operator', gudang='Gudang 2') as c:
        original = c.request
        requests = 0
        async def request(method, url, **kw):
            nonlocal requests
            if urlsplit(str(url)).path == '/api/actions/lini-produksi':
                requests += 1
                return httpx.Response(status, json={'detail':'Izin gudang berubah; pilih gudang kerja yang sesuai.'})
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_penyosohan')
            await expect(page.locator('#galat_pilihan_lini_id')).to_contain_text('Izin gudang berubah')
            await expect(page.locator('#lembar')).to_be_visible()
            assert '/masuk' not in page.url
            # Silo dari pembacaan pertama tetap dapat dibaca; penolakan alat
            # tidak mengganti halaman atau mengirim ulang penulisan.
            await expect(page.locator('#b_silo input[value=B]')).to_have_count(1)
            await page.locator('#b_silo input[value=B]').check()
            await page.locator('#simpan').click()
            await expect(page.locator('#lembar')).to_contain_text('Izin gudang berubah')
            await expect(page.locator('#b_silo input[value=B]')).to_be_checked()
            await page.wait_for_timeout(1300)
            assert requests == 1


async def test_pilihan_silo_403_tidak_dianggap_gangguan_jaringan(pg, gudang2):
    from playwright.async_api import expect
    await seed_master()
    async with await _klien(pg, peran='operator', gudang='Gudang 2') as c:
        original = c.request
        async def request(method, url, **kw):
            path = urlsplit(str(url))
            if path.path == '/api/actions/silo-bahan-g2' and 'lini_id=' in path.query:
                return httpx.Response(403, json={'detail':'Akses silo ditolak untuk gudang ini.'})
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_penyosohan')
            await expect(page.locator('[data-galat-akses]')).to_contain_text('Akses silo ditolak')
            await expect(page.locator('#simpan')).to_be_disabled()
            assert '/masuk' not in page.url
            assert 'dipulihkan otomatis' not in await page.locator('#b_silo').inner_text()


async def test_pencarian_pelanggan_pulih_tanpa_membuang_ketikan(pg, gudang2):
    from playwright.async_api import expect
    await seed_master()
    async with await _klien(pg, peran='admin') as c:
        original = c.request
        requests = 0
        async def request(method, url, **kw):
            nonlocal requests
            if urlsplit(str(url)).path == '/api/actions/pelanggan-kledo':
                requests += 1
                return httpx.Response(503, json={'detail':'Sementara.'}) if requests == 1 else httpx.Response(200, json=[{'value':'71','label':'Pelanggan Uji'}])
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=pindah_kepemilikan_karung')
            await expect(page.locator('#galat_pilihan_pelanggan')).to_contain_text('Dicoba lagi otomatis')
            await page.locator('#x_pelanggan').fill('Pelanggan')
            await expect(page.locator('#galat_pilihan_pelanggan')).to_have_count(0)
            await expect(page.locator('#x_pelanggan')).to_have_value('Pelanggan')
            await page.locator('#x_pelanggan').fill('Pelanggan U')
            await expect(page.locator('#c_pelanggan')).to_contain_text('Pelanggan Uji')


async def test_barang_berulang_pulih_dengan_jumlah_yang_sudah_diketik(pg, gudang2):
    from playwright.async_api import expect
    await seed_master()
    async with await _klien(pg, peran='admin') as c:
        original = c.request
        requests = 0
        async def request(method, url, **kw):
            nonlocal requests
            path = urlsplit(str(url)).path
            if path == '/api/actions/perintah-bisa-ditambah':
                return httpx.Response(200, json=[{'value':'71','label':'Pelanggan Uji'}])
            if path == '/api/actions/barang-tambahan-perintah':
                requests += 1
                return httpx.Response(503, json={'detail':'Sementara.'}) if requests == 1 else httpx.Response(200, json=[{'value':'pk_g2:1','label':'PK pelanggan uji'}])
            return await original(method, url, **kw)
        c.request = request
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=tambah_barang_keluar')
            await page.locator('#f_perintah').select_option('71')
            await expect(page.locator('#galat_pilihan_barang')).to_contain_text('Dicoba lagi otomatis')
            amount = page.locator('[data-ulang-untuk=barang] input[data-p-jenis=angka]').first
            await amount.fill('123')
            await expect(page.locator('#galat_pilihan_barang')).to_have_count(0)
            await expect(amount).to_have_value('123')
            await expect(page.locator('[data-ulang-untuk=barang] select').first).to_contain_text('PK pelanggan uji')


@pytest.mark.parametrize('peran', ['operator','admin','superadmin'])
@pytest.mark.parametrize('width', [390,1440])
async def test_tombol_kartu_silo_memulai_giling_dengan_alat_yang_benar(pg,silos,peran,width):
    from playwright.async_api import expect
    from urllib.parse import parse_qs
    from sqlalchemy import select,func
    from app.models import MillingProcess
    await seed_master()
    async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
        async with browser(c,width) as page:
            await page.route('**/api/aliran',lambda r:r.abort())
            errors=[]
            page.on('response',lambda r:errors.append(r.status) if '/api/actions/' in r.url and r.status>=400 else None)
            await page.goto('https://uji/pekerjaan' if peran=='operator' else 'https://uji/')
            if peran!='operator':
                await page.locator('a[href="/gudang/g1"]').first.click()
            link=page.locator('a[href*="buka=mulai_giling"][href*="nilai="]').first
            await link.wait_for(state='attached')
            nama=parse_qs(urlsplit(await link.get_attribute('href')).query)['nilai'][0]
            if not await link.is_visible():
                await link.locator('xpath=ancestor::details[1]/summary').click()
            await link.click()
            await expect(page.locator('#alat_otomatis_lini_id')).to_contain_text('Penggilingan 1')
            assert (await page.locator('#f_lini_id').input_value()).isdigit()
            await expect(page.locator('#b_silo input[value='+json.dumps(nama)+']')).to_be_checked()
            await expect(page.get_by_role('button',name='Muat ulang pilihan silo',exact=True)).to_have_count(0)
            await page.locator('#simpan').click()
            await expect(page.locator('#lembar')).not_to_be_visible()
            assert not errors,errors
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(MillingProcess))==1
        proc=await db.scalar(select(MillingProcess))
        assert proc.silo_id in silos['silo'].values()


async def test_stream_realtime_tidak_menggantung_transport_browser_uji(pg,gudang2):
    await seed_master()
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        original=c.request
        streams=[]
        async def request(method,url,**kw):
            if urlsplit(str(url)).path=='/api/aliran':
                streams.append(str(url))
                raise AssertionError('SSE tidak dapat dibuffer oleh ASGITransport.')
            return await original(method,url,**kw)
        c.request=request
        async with browser(c,390) as page:
            await page.goto('https://uji/pekerjaan')
            result=await page.evaluate("""() => new Promise((resolve,reject) => {
                const stream=new EventSource('/api/aliran');
                const timer=setTimeout(() => {stream.close();reject(new Error('Stream menggantung'));},5000);
                stream.onerror=() => {clearTimeout(timer);stream.close();resolve('selesai');};
            })""")
            assert result=='selesai'
            assert not streams


async def test_browser_menuntaskan_permintaan_sebelum_database_uji_dibersihkan(pg,gudang2):
    from sqlalchemy import select
    from app.models import User
    await seed_master()
    started=asyncio.Event();finished=asyncio.Event()
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        original=c.request
        async def request(method,url,**kw):
            if urlsplit(str(url)).path=='/api/tes-lambat':
                async with pg() as db:
                    await db.scalar(select(User.id).limit(1))
                    started.set()
                    await asyncio.sleep(.5)
                finished.set()
                return httpx.Response(200,json={'selesai':True})
            return await original(method,url,**kw)
        c.request=request
        async with browser(c,390) as page:
            await page.goto('https://uji/pekerjaan')
            await page.evaluate("() => { fetch('/api/tes-lambat').catch(() => {}); }")
            await asyncio.wait_for(started.wait(),timeout=5)
        assert finished.is_set(),'Permintaan masih memegang transaksi saat browser uji ditutup.'
