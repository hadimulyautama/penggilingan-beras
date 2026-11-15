"""Kandidat Transfer: hak tindakan, pembacaan aman, dan draft tidak hilang.

Browser memakai sesi uji nyata beserta kuki/token CSRF browser_app; hanya
respons pembacaan dan gangguan jaringan tertentu yang disimulasikan.
"""
import asyncio
import copy
import json
import re
from urllib.parse import urlsplit

import pytest
from playwright.async_api import expect
from sqlalchemy import func, select

from app.models import FinishedGoodsStock, InternalTransfer, PermintaanPk, PengirimanPk
from app.services import transfer
from tests.pg.test_kepemilikan_koreksi import world  # fixture dependency
from tests.pg.test_pengiriman_pk_bertahap import siap, lot_lain
from tests.pg.test_permintaan_empat_langkah import pabrik  # fixture dependency
from tests.pg.test_transfer_barang import lokasi
from tests.pg.test_transfer_pk_halaman import BASE, browser_app
from tests.pg.test_transfer_pk_multilokasi import antar_pabrik

pytestmark = pytest.mark.asyncio
READ = BASE + '/api/transfer-bertahap'


class Snapshot:
    """Respons GET terkendali; tidak pernah mengintersep POST."""
    def __init__(self, payload):
        self.payload = copy.deepcopy(payload)
        self.gagal = False
        self.selesai = asyncio.Queue()

    async def route(self, route):
        if route.request.method != 'GET':
            await route.fallback()
            return
        await route.fulfill(
            status=503 if self.gagal else 200,
            content_type='application/json',
            body=json.dumps({'detail': 'Pembacaan sementara gagal.'}
                            if self.gagal else self.payload),
        )
        self.selesai.put_nowait(True)

    async def baca(self, page, event='transfer-baca-segar'):
        if event == 'transfer-baca-segar':
            await page.locator('#transfer-pk').evaluate(
                '(e)=>e.dispatchEvent(new Event("transfer-baca-segar"))')
        else:
            await page.evaluate('(e)=>window.dispatchEvent(new Event(e))', event)
        await asyncio.wait_for(self.selesai.get(), timeout=5)
        # Fulfill selesai dahulu; beri fetch dan render kesempatan menyelesaikan.
        await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def snapshot(page, client):
    response = await client.get('/api/transfer-bertahap')
    assert response.status_code == 200, response.text
    state = Snapshot(response.json())
    await page.route(READ, state.route)
    return state


def catat_post(page):
    requests = []
    page.on('request', lambda r: requests.append(r) if r.method == 'POST' else None)
    return requests


async def buka_sumber_pk(page, lot):
    await expect(page.locator('#tb-pesan')).to_contain_text('sumber tersedia')
    await page.locator('#tb-cari-form [name=jenis]').select_option('pk_giling')
    await page.locator('#tb-cari-form [name=cari]').fill(lot)
    await page.locator('#tb-cari-form').get_by_role('button', name='Cari sumber').click()
    await page.locator('#tb-sumber article').filter(has_text=lot).get_by_role(
        'button', name='Pilih sumber ini', exact=True).click()


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('peran,gudang,admin', [
    ('admin', None, True), ('superadmin', None, True),
    ('operator', 'Gudang 1', False), ('operator', 'Gudang 2', False),
])
async def test_tindakan_utama_dan_daftar_shared_sesuai_peran(pg, siap, width, peran, gudang, admin):
    async with browser_app(pg, peran=peran, gudang=gudang, width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        await expect(page.locator('#pk-muat')).to_have_count(0)
        await expect(page.get_by_role('link', name='Pilih bahan baku', exact=True)).to_have_count(0)
        await expect(page.locator('#tp-coba-lagi')).not_to_be_visible()
        if admin:
            await expect(page.locator('#tb-buka')).to_be_visible()
            await expect(page.locator('#tb-buka')).to_have_text('Perintah Transfer')
            await expect(page.locator('#tp-minta-konteks')).not_to_be_visible()
        else:
            await expect(page.locator('#tb-buka')).not_to_be_visible()
            await expect(page.locator('#tp-minta-konteks')).to_be_visible()
        if width < 768:
            await expect(page.locator('#pk-daftar .riwayat-list .padat:visible')).to_have_count(1)
        else:
            await expect(page.locator('#pk-daftar .riwayat-desktop-grid:visible')).not_to_have_count(0)
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')


async def test_gagal_baca_menandai_data_lama_lalu_retry_hanya_get(pg, siap):
    async with browser_app(pg) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        posts = catat_post(page)
        state = await snapshot(page, client)
        state.gagal = True
        await state.baca(page)
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'gagal')
        await expect(page.locator('#tp-coba-lagi')).to_be_visible()
        await expect(page.locator('#pk-daftar')).to_contain_text(siap['lot'])
        state.gagal = False
        for row in state.payload['permintaan']:
            row['pemilik'] = 'Pemilik setelah pulih'
        await page.locator('#tp-coba-lagi').click()
        await asyncio.wait_for(state.selesai.get(), timeout=5)
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        await expect(page.locator('#tp-coba-lagi')).not_to_be_visible()
        await expect(page.locator('#pk-daftar')).to_contain_text('Pemilik setelah pulih')
        assert posts == []


async def test_pencarian_filter_fokus_dan_pilihan_menahan_snapshot_baru(pg, siap):
    await lot_lain(pg, siap)
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap?status=siap&cari=LOT-MINTA')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        state = await snapshot(page, client)
        posts = catat_post(page)
        for row in state.payload['permintaan']:
            row['pemilik'] = 'Snapshot fokus baru'
        await page.locator('#pk-cari').focus()
        await state.baca(page, 'focus')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'tertunda')
        await expect(page.locator('#pk-cari')).to_be_focused()
        await expect(page.locator('#pk-cari')).to_have_value('LOT-MINTA')
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Snapshot fokus baru')
        await expect(page.locator('#pk-ringkasan')).to_contain_text('Siap dipindahkan')
        await page.locator('#pk-cari').blur()
        await expect(page.locator('#pk-daftar')).to_contain_text('Snapshot fokus baru')
        await expect(page).to_have_url(re.compile(r'status=siap.*cari=LOT-MINTA'))
        checkbox = page.locator('#pk-daftar [name=pilih]:visible').first
        await checkbox.check()
        for row in state.payload['permintaan']:
            row['pemilik'] = 'Snapshot pilihan baru'
        await state.baca(page)
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'tertunda')
        await expect(checkbox).to_be_checked()
        await expect(page.locator('#pk-terpilih')).to_contain_text('1 permintaan dipilih')
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Snapshot pilihan baru')
        await page.locator('#pk-bersihkan').click()
        await expect(page.locator('#pk-daftar')).to_contain_text('Snapshot pilihan baru')
        await expect(page.locator('#pk-cari')).to_have_value('LOT-MINTA')
        assert posts == []


async def test_dialog_catatan_mempertahankan_draft_dan_fokus_sampai_ditutup(pg, siap):
    async with browser_app(pg) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        state = await snapshot(page, client)
        posts = catat_post(page)
        await page.locator('#pk-daftar [data-catatan]:visible').first.click()
        bags = page.locator('#pk-form [name=jumlah_karung]')
        curah = page.locator('#pk-form [name=berat_curah_kg]')
        await bags.fill('17')
        await curah.fill('2.75')
        for row in state.payload['permintaan']:
            row['pemilik'] = 'Snapshot dialog baru'
        await state.baca(page, 'focus')
        await state.baca(page)
        await expect(page.locator('#pk-form')).to_be_visible()
        await expect(bags).to_have_value('17')
        await expect(curah).to_have_value('2.75')
        await expect(curah).to_be_focused()
        await expect(page.locator('#pk-form-total')).to_contain_text('852,75 kg')
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Snapshot dialog baru')
        await page.get_by_role('button', name='Tutup formulir', exact=True).click()
        source_action = page.locator('#pk-daftar [data-catatan]:visible').first
        await expect(source_action).to_be_focused()
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'tertunda')
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Snapshot dialog baru')
        # Keyboard mengikuti siklus dialog yang sama; fokus kembali ke
        # tindakan asal sehingga pembacaan tetap belum mengganti kartunya.
        await page.keyboard.press('Enter')
        await expect(page.locator('#pk-form')).to_be_visible()
        await page.keyboard.press('Escape')
        await expect(page.locator('#pk-form')).not_to_be_visible()
        await expect(source_action).to_be_focused()
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'tertunda')
        await page.locator('#pk-filter-buka').focus()
        await expect(page.locator('#pk-daftar')).to_contain_text('Snapshot dialog baru')
        await expect(page.locator('#pk-filter-buka')).to_be_focused()
        assert posts == []


async def test_refresh_tidak_mengulang_post_atau_mengganti_nonce_draft_permohonan(pg, lokasi):
    # Operator penerima hanya meminta barang pabrik yang dapat dibaca lintas
    # gudang. Barang pelanggan milik fixture tetap mengikuti pagar izinnya.
    async with pg() as db:
        factory_id = await db.scalar(select(FinishedGoodsStock.id).where(
            FinishedGoodsStock.warehouse_id == lokasi['wh'],
            FinishedGoodsStock.jasa_id.is_(None),
        ))
        assert factory_id is not None
    async with browser_app(pg, gudang='Gudang 1') as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        state = await snapshot(page, client)
        await page.locator('#tp-minta-konteks').click()
        await expect(page.locator('#tb-pesan')).to_contain_text('sumber tersedia')
        await page.locator('#tb-cari-form [name=jenis]').select_option('barang')
        async with page.expect_response(lambda r: '/api/transfer-barang/sumber?' in r.url) as response:
            await page.locator('#tb-cari-form').get_by_role('button', name='Cari sumber').click()
        payload = await (await response.value).json()
        eligible = [row for row in payload['items'] if row['asal_id'] != lokasi['target']]
        index = next(i for i, row in enumerate(eligible) if row['id'] == str(factory_id))
        await page.locator(f'#tb-sumber [data-tb-sumber="{index}"]').click()
        await page.locator('#tb-form [name=jumlah]').fill('20')
        await expect(page.locator('#tb-form [name=gudang]')).to_have_value(str(lokasi['target']))
        await expect(page.locator('#tb-form [name=gudang]')).to_be_disabled()
        posts = []
        async def gagal(route):
            if route.request.method == 'POST':
                posts.append(route.request.post_data_json)
                await route.fulfill(status=503, content_type='application/json', body='{"detail":"Koneksi putus."}')
            else:
                await route.fallback()
        await page.route(BASE + '/api/transfer-barang/permintaan', gagal)
        await page.locator('#tb-simpan').click()
        await expect(page.locator('#tb-pesan')).to_contain_text('Isian dikunci')
        await state.baca(page, 'focus')
        await state.baca(page)
        assert len(posts) == 1
        await expect(page.locator('#tb-form [name=jumlah]')).to_have_value('20')
        await expect(page.locator('#tb-form [name=jumlah]')).to_be_disabled()
        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/transfer-barang/permintaan'):
            await page.locator('#tb-simpan').click()
        await expect(page.locator('#tb-pesan')).to_contain_text('Isian dikunci')
        assert len(posts) == 2 and posts[0] == posts[1]
        assert posts[0]['kunci']
        assert posts[0]['tujuan_id'] == lokasi['target']
        assert posts[0]['sumber_id'] == str(factory_id)


async def test_permintaan_pk_lama_tetap_dimulai_dari_detail_sumber(pg, pabrik):
    async with browser_app(pg, gudang='Gudang 2') as (page, _, _):
        await page.goto(BASE + '/stok?tab=bahan')
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


@pytest.mark.parametrize('width', [390, 1440])
async def test_perintah_admin_siap_tanpa_stok_lalu_operator_asal_mencatat(pg, antar_pabrik, width):
    w = antar_pabrik
    async with browser_app(pg, peran='admin', gudang=None, width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await page.locator('#tb-buka').click()
        await buka_sumber_pk(page, w['lot'])
        await page.locator('#tb-form [name=karung_pk]').fill('23')
        await page.locator('#tb-form [name=curah_pk]').fill('2')
        await page.locator('#tb-form [name=pabrik]').select_option(str(w['pabrik_tujuan']))
        await page.locator('#tb-tujuan-lokasi').select_option('silo:' + str(w['silo_tujuan']))
        await expect(page.locator('#tb-simpan')).to_have_text('Terbitkan perintah')
        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/transfer-barang/perintah') as response:
            await page.locator('#tb-simpan').click()
        issued = await response.value
        assert issued.status == 200, await issued.text()
        rid = (await issued.json())['id']
        await expect(page.locator('#tb-panel')).not_to_be_visible()
        await expect(page.locator('#pk-daftar')).to_contain_text('Siap dipindahkan')
        await expect(page.locator('#pk-daftar')).to_contain_text('1.152 kg')
    async with pg() as db:
        request = await db.get(PermintaanPk, rid)
        assert request.status == 'disetujui'
        assert request.berat_setuju_kg == 1152
        assert request.silo_id == w['silo_tujuan']
        assert await transfer.saldo_pk(db, w['proses_id']) == 6000
        assert await db.scalar(select(func.count()).select_from(InternalTransfer)) == 0
        assert await db.scalar(select(func.count()).select_from(PengirimanPk)) == 0
    async with browser_app(pg, gudang='Gudang PK Pabrik Tujuan', width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#pk-daftar')).to_contain_text(w['lot'])
        await expect(page.locator('#pk-daftar [data-catatan]:visible')).to_have_count(0)
    async with browser_app(pg, gudang='Gudang 1', width=width) as (page, _, _):
        await page.goto(BASE + '/transfer-bertahap')
        await page.locator('#pk-daftar [data-catatan]:visible').first.click()
        await expect(page.locator('#pk-form [name=jumlah_karung]')).to_have_value('23')
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-pesan')).to_contain_text('Stok asal dan tujuan sudah diperbarui')
    async with pg() as db:
        assert await transfer.saldo_pk(db, w['proses_id']) == 4848
        assert await db.scalar(select(func.sum(InternalTransfer.berat_kg))) == 1152
        assert await db.scalar(select(func.count()).select_from(PengirimanPk)) == 1


async def test_get_lama_tidak_menimpa_perintah_yang_baru_tersimpan(pg, antar_pabrik):
    """Generasi baca tetap menjaga hasil POST bila transport terlambat selesai.

    GET pertama sengaja tetap menyelesaikan Promise meskipun sinyal dibatalkan,
    sehingga uji juga membuktikan pagar generasi, bukan hanya AbortController.
    POST dan GET sesudah commit tetap melewati browser_app dan CSRF nyata.
    """
    w = antar_pabrik
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        old = (await client.get('/api/transfer-bertahap')).json()
        assert old['permintaan'] == []
        await page.locator('#tb-buka').click()
        await buka_sumber_pk(page, w['lot'])
        await page.locator('#tb-form [name=karung_pk]').fill('20')
        await page.locator('#tb-form [name=curah_pk]').fill('0')
        await page.locator('#tb-form [name=pabrik]').select_option(str(w['pabrik_tujuan']))
        await page.locator('#tb-tujuan-lokasi').select_option('gudang:' + str(w['target']))
        posts = catat_post(page)
        await page.evaluate('''(old)=>{
            const nativeFetch=window.fetch;
            let held=false;
            window.fetch=(input,init)=>{
                if(input==='/api/transfer-bertahap' && !held &&
                    (!init?.method || init.method==='GET')){
                    held=true;
                    return new Promise(resolve=>{
                        window.releaseTransferRead=()=>resolve(new Response(
                            JSON.stringify(old),{status:200,headers:{'Content-Type':'application/json'}}));
                    });
                }
                return nativeFetch.call(window,input,init);
            };
        }''', old)
        await page.locator('#transfer-pk').evaluate(
            '(e)=>e.dispatchEvent(new Event("transfer-baca-segar"))')
        await page.wait_for_function('typeof window.releaseTransferRead==="function"')
        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/transfer-barang/perintah') as response:
            await page.locator('#tb-simpan').click()
        issued = await response.value
        assert issued.status == 200, await issued.text()
        rid = (await issued.json())['id']
        await expect(page.locator('#tb-panel')).not_to_be_visible()
        await expect(page.locator('#pk-daftar')).to_contain_text(w['lot'])
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'segar')
        await page.evaluate('''async()=>{
            window.releaseTransferRead();
            await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
        }''')
        await expect(page.locator('#pk-daftar')).to_contain_text('Siap dipindahkan')
        retained = await page.locator('#transfer-pk').evaluate('e=>e._transferData.permintaan')
        assert len(retained) == 1 and retained[0]['id'] == rid
        assert retained[0]['status'] == 'disetujui'
        assert len(posts) == 1
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PermintaanPk)) == 1
        assert await db.scalar(select(func.count()).select_from(InternalTransfer)) == 0
        assert await transfer.saldo_pk(db, w['proses_id']) == 6000
