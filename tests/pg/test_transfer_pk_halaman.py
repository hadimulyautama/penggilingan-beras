"""Alur pada satu halaman; browser sungguhan dengan stok PostgreSQL terisolasi."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from sqlalchemy import select, func
from app.models import User, PermintaanPk, InternalTransfer, PengirimanPk, Silo
from app.services import pengiriman_pk as s, permintaan_pk as m, transfer
from tests.pg.test_pengiriman_pk_bertahap import siap, lot_lain
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio
BASE = 'http://127.0.0.1:59996'


@asynccontextmanager
async def browser_app(pg, *, peran='operator', gudang='Gudang 1', width=390, putus=False):
    from playwright.async_api import async_playwright
    async with await _klien(pg, peran=peran, gudang=gudang) as client, async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport=dict(width=width, height=1000))
        errors, kiriman = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def app(route):
            req = route.request
            url = urlsplit(req.url)
            if not req.url.startswith(BASE + '/'):
                await route.abort()
                return
            if url.path == '/api/aliran':
                await route.fulfill(status=204, body='')
                return
            response = await client.request(req.method, url.path + ('?' + url.query if url.query else ''),
                content=req.post_data_buffer, headers={k:v for k,v in req.headers.items()
                    if k.lower() in ('content-type', 'x-csrf-token', 'x-pindah')})
            if req.method == 'POST' and url.path.endswith('/pengiriman'):
                kiriman.append(req.post_data_json)
                # Respons hilang SESUDAH writer commit, kasus retry terberat.
                if putus and len(kiriman) == 1:
                    assert response.status_code == 200, response.text
                    await route.abort('connectionfailed')
                    return
            await route.fulfill(status=response.status_code, headers={k:v for k,v in response.headers.items()
                if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')}, body=response.content)
        await page.context.add_cookies([dict(name=x.name, value=x.value, url=BASE) for x in client.cookies.jar])
        await page.route('**/*', app)
        try:
            yield page, client, kiriman
            assert not errors, errors
        finally:
            await browser.close()


@pytest.mark.parametrize('width', [320, 390, 1440])
@pytest.mark.parametrize('peran,gudang,jumlah,status', [
    ('admin', None, 2, 'Semua status'),
    ('operator', 'Gudang 1', 2, 'Semua status'),
    ('operator', 'Gudang 2', 2, 'Semua status'),
    ('superadmin', None, 2, 'Semua status'),
])
async def test_menu_tab_filter_dan_cakupan_peran(pg, siap, width, peran, gudang, jumlah, status):
    from playwright.async_api import expect
    await lot_lain(pg, siap)
    async with browser_app(pg, peran=peran, gudang=gudang, width=width) as (page, _, _):
        await page.goto(BASE + '/pekerjaan')
        link = page.locator('#laci').get_by_role('link', name='Transfer', exact=True)
        if not await link.is_visible():
            await page.get_by_role('button', name='Buka menu', exact=True).click()
        await link.click()
        await expect(page.locator('#pk-pesan')).to_have_text('Status diperbarui.')
        await expect(page.locator('#pk-daftar article')).to_have_count(jumlah)
        await expect(page.locator('#pk-ringkasan')).to_contain_text(status)
        await expect(page.locator('#laci a[href="/transfer-bertahap"]')).to_have_attribute('aria-current', 'page')
        await expect(page.locator('.pintu__ikon--transfer_pk svg')).to_have_count(1)
        assert await page.locator('.kontrol-tab__item').first.evaluate('e=>e.getBoundingClientRect().height') == 64
        await page.get_by_role('button', name='Filter', exact=False).click()
        await expect(page.locator('#pk-filter [name=status]')).to_have_value('')
        await page.locator('#pk-filter [name=status]').select_option('siap')
        await page.get_by_role('button', name='Terapkan filter', exact=True).click()
        await expect(page.locator('#pk-daftar article')).to_have_count(1)
        await page.get_by_role('button', name='Filter', exact=False).click()
        await page.locator('#pk-filter [name=status]').select_option('')
        await page.get_by_role('button', name='Terapkan filter', exact=True).click()
        await expect(page.locator('#pk-daftar article')).to_have_count(2)
        await page.locator('#pk-cari').fill('lot-lain')
        await expect(page.locator('#pk-daftar article')).to_have_count(1)
        await page.reload()
        await expect(page.locator('#pk-daftar article')).to_have_count(1)
        await expect(page.locator('#pk-cari')).to_have_value('lot-lain')
        await page.locator('#pk-cari').fill('<img src=x onerror=alert(1)>')
        await expect(page.locator('#pk-daftar .tp-kosong')).to_be_visible()
        await page.get_by_role('button', name='Tampilkan semua', exact=True).click()
        if gudang == 'Gudang 2':
            await expect(page.locator('[data-catatan],[name=pilih]')).to_have_count(0)
            await page.locator('#pk-daftar').get_by_role('button', name='Lihat detail', exact=True).first.click()
            await expect(page.locator('[data-action],[data-koreksi]')).to_have_count(0)
            await page.get_by_role('button', name='Tutup detail', exact=True).click()
            await expect(page.get_by_role('link', name='Pilih bahan baku', exact=True)).to_have_attribute('href', '/stok?tab=bahan')
        await page.get_by_role('link', name='Riwayat transfer', exact=False).click()
        await expect(page.locator('#pk-permintaan')).not_to_be_visible()
        await expect(page.locator('#pk-perjalanan')).to_be_visible()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('width', [390, 1440])
async def test_persetujuan_banyak_tujuan_berbeda_tidak_memindahkan_stok(pg, pabrik, width):
    from playwright.async_api import expect
    async with pg() as db:
        r = await m.minta(db, user=await db.get(User, pabrik['op2']), kode_proses=pabrik['lot'], berat=6000)
        rid = r.id
    rid2 = await lot_lain(pg, pabrik)
    async with browser_app(pg, peran='admin', gudang=None, width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#pk-daftar article')).to_have_count(2)
        await expect(page.locator('#pk-form')).not_to_be_visible()
        await page.locator('[name=pilih]').nth(0).check()
        await page.locator('[name=pilih]').nth(1).check()
        await page.locator('#pk-buka-form').click()
        rows = page.locator('#pk-form-lot .tp-form-row')
        await rows.nth(0).locator('[name=berat]').fill('4000')
        await rows.nth(1).locator('[name=tujuan]').select_option('Silo A')
        await expect(page.locator('#pk-form-total')).to_contain_text('7.000 kg')
        Path('tmp').mkdir(exist_ok=True)
        await page.screenshot(path=f'tmp/transfer-pk-persetujuan-{width}.png', full_page=True)
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-pesan')).to_contain_text('telah disetujui')
        await expect(page.locator('#pk-daftar article')).to_have_count(2)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(InternalTransfer)) == 0
        assert await transfer.saldo_pk(db, pabrik['proses_id']) == 6000
        assert (await db.get(PermintaanPk, rid)).berat_setuju_kg == 4000
        assert (await db.get(PermintaanPk, rid2)).silo_id is not None
    async with browser_app(pg, width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('[name=pilih]')).to_have_count(2)
        await page.locator('[name=pilih]').nth(0).check()
        await page.locator('[name=pilih]').nth(1).check()
        await expect(page.locator('#pk-buka-form')).to_be_disabled()
        await expect(page.locator('#pk-pilihan-pesan')).to_contain_text('asal, tujuan, dan pemilik yang sama')


async def test_koneksi_putus_sesudah_commit_tetap_satu_transfer(pg, siap):
    from playwright.async_api import expect
    async with browser_app(pg, putus=True) as (page, _, kiriman):
        await page.goto(BASE + '/transfer-bertahap')
        await page.locator('[data-catatan]').click()
        await page.locator('[name=jumlah_karung]').fill('20')
        await page.locator('[name=berat_curah_kg]').fill('2')
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-form-pesan')).to_contain_text('Isian dikunci')
        await expect(page.locator('[name=jumlah_karung]')).to_have_value('20')
        await expect(page.locator('[name=jumlah_karung]')).to_be_disabled()
        await page.keyboard.press('Escape')
        await expect(page.locator('#pk-form')).to_be_visible()
        await page.get_by_role('button', name='Ulangi pencatatan', exact=True).click()
        await expect(page.locator('#pk-pesan')).to_contain_text('Stok asal dan tujuan sudah diperbarui')
        assert len(kiriman) == 2 and kiriman[0] == kiriman[1]
        await page.get_by_role('link', name='Permintaan lot', exact=False).click()
        await expect(page.locator('#pk-daftar article')).to_have_count(1)
        await expect(page.locator('#pk-daftar')).to_contain_text('Dipindahkan sebagian')
        await page.reload()
        await expect(page.locator('#pk-daftar')).to_contain_text('Dipindahkan sebagian')
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PengirimanPk)) == 1
        assert await db.scalar(select(func.sum(InternalTransfer.berat_kg))) == 1002
        assert await transfer.saldo_pk(db, siap['proses_id']) == 4998


async def test_penutupan_sisa_terlihat_di_status_ditutup_dan_alasan_tidak_hilang(pg, siap):
    from playwright.async_api import expect
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap?status=perlu_transfer')
        await page.get_by_role('button', name=f"Tindakan permintaan {siap['rid']}", exact=True).click()
        await page.get_by_role('button', name='Tutup sisa persetujuan', exact=True).click()
        await page.locator('#pk-alasan [name=alasan]').fill('Kebutuhan dibatalkan setelah pemeriksaan')
        # Tolak satu kali untuk membuktikan alasan dan galat ada di panel aktif.
        async def gagal(route):
            await route.fulfill(status=409, content_type='application/json', body='{"detail":"Catatan sedang berubah, periksa lagi."}')
        endpoint = BASE + f"/api/transfer-bertahap/permintaan/{siap['rid']}/tutup-sisa"
        await page.route(endpoint, gagal)
        await page.get_by_role('button', name='Simpan keputusan', exact=True).click()
        await expect(page.locator('#pk-alasan-pesan')).to_contain_text('Catatan sedang berubah')
        await expect(page.locator('#pk-alasan [name=alasan]')).to_have_value('Kebutuhan dibatalkan setelah pemeriksaan')
        await page.unroute(endpoint, gagal)
        await page.get_by_role('button', name='Simpan keputusan', exact=True).click()
        await expect(page.locator('#pk-pesan')).to_have_text('Keputusan tersimpan.')
        await page.locator('#pk-filter-buka').click()
        await page.locator('#pk-filter [name=status]').select_option('ditutup')
        await page.get_by_role('button', name='Terapkan filter', exact=True).click()
        await expect(page.locator('#pk-daftar')).to_contain_text('Sisa ditutup')
        await page.get_by_role('button', name='Lihat detail', exact=True).click()
        await expect(page.locator('#pk-detail')).to_contain_text('Kebutuhan dibatalkan setelah pemeriksaan')
        assert (await client.get('/api/transfer-bertahap')).json()['permintaan'][0]['sisa'] == '6000'
    async with pg() as db:
        assert await transfer.saldo_pk(db, siap['proses_id']) == 6000


async def test_permintaan_tetap_dari_detail_bahan_baku(pg, pabrik):
    from playwright.async_api import expect
    async with browser_app(pg, gudang='Gudang 2') as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await page.get_by_role('link', name='Pilih bahan baku', exact=True).click()
        await page.locator('a[href^="/stok/pk/detail"][href*="LOT-MINTA-01"]:visible').first.click()
        await page.get_by_role('link', name='Minta lot ini', exact=True).click()
        await expect(page.locator('#lembar')).to_be_visible()
        await page.locator('#f_jumlah_karung').fill('23')
        await page.locator('#f_berat_curah_kg').fill('2')
        await page.get_by_role('button', name='Minta PK', exact=True).click()
        await expect(page.locator('#lembar')).not_to_be_visible()
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#pk-daftar')).to_contain_text('1.152 kg')
        await expect(page.locator('#pk-daftar')).to_contain_text('Menunggu Admin')
    async with pg() as db:
        assert await transfer.saldo_pk(db, pabrik['proses_id']) == 6000
        assert await db.scalar(select(func.count()).select_from(InternalTransfer)) == 0
        assert (await db.scalar(select(PermintaanPk))).berat_minta_kg == 1152


@pytest.mark.parametrize('width', [390, 1024, 1440])
async def test_daftar_responsif_sidebar_tema_dan_cetak(pg, siap, width):
    from playwright.async_api import expect
    await lot_lain(pg, siap)
    async with browser_app(pg, peran='admin', gudang=None, width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap?status=')
        await expect(page.locator('#pk-daftar article')).to_have_count(2)
        for lebar in [280, 440]:
            await page.evaluate('(w)=>document.documentElement.style.setProperty("--sidebar",w+"px")', lebar)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert await page.locator('#pk-daftar').evaluate('e=>e.scrollWidth<=e.clientWidth')
        await page.evaluate('document.documentElement.style.removeProperty("--sidebar")')
        Path('tmp').mkdir(exist_ok=True)
        await page.screenshot(path=f'tmp/transfer-pk-daftar-{width}.png', full_page=True)
        await page.get_by_role('button', name='Panduan', exact=True).click()
        await expect(page.locator('#pk-panduan')).to_contain_text('Minta lot ini')
        await page.locator('#pk-panduan [data-tutup]').click()
        await page.evaluate('()=>{document.body.classList.remove("terik");window.cetakan=0;window.print=()=>window.cetakan++}')
        await page.get_by_role('button', name='Cetak', exact=True).click()
        assert await page.evaluate('window.cetakan') == 1
        await page.emulate_media(media='print')
        await expect(page.locator('#pk-perjalanan')).not_to_be_visible()
        await expect(page.locator('#pk-daftar article')).to_have_count(2)
        await expect(page.locator('#pk-daftar article').first).to_be_visible()
        await expect(page.locator('.kontrol-halaman')).not_to_be_visible()
