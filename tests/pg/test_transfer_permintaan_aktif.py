"""Kelompok permintaan mengikuti workflow nyata; browser hanya membaca fixture."""
import os
import re
import uuid
from pathlib import Path

import pytest
from playwright.async_api import expect
from sqlalchemy import select

from app.models import FinishedGoodsStock, User
from app.services import perintah_transfer, transfer_barang as barang
from tests.pg.test_kepemilikan_koreksi import world  # fixture dependency
from tests.pg.test_transfer_barang import lokasi, minta, approve, catat
from tests.pg.test_transfer_pk_halaman import browser_app, BASE
from tests.pg.test_transfer_kandidat_browser import snapshot, catat_post
from tests.pg.test_pengiriman_pk_bertahap import siap, pabrik, buat
from tests.pg.test_pengaturan_organisasi import fakta

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def campuran(pg, lokasi):
    w = lokasi
    async with pg() as db:
        source = await db.scalar(select(FinishedGoodsStock).where(
            FinishedGoodsStock.warehouse_id == w['wh'], FinishedGoodsStock.jasa_id.is_(None)))
        sid = source.id
    ids = {}
    ids['pending'] = await minta(pg, w, 'barang', sid, 2)
    async with pg() as db:
        result = await perintah_transfer.buat(db, user=await db.get(User, w['user']),
            jenis='barang', sumber_id=str(sid), jumlah='2', asal_id=w['wh'],
            tujuan_id=w['target'], kunci=uuid.uuid4().hex)
        ids['ready'] = -result['id']
    for name in ['partial', 'done', 'rejected', 'closed', 'partial_closed']:
        rid = ids[name] = await minta(pg, w, 'barang', sid, 2)
        if name != 'rejected':
            await approve(pg, w, rid, 2)
        if name in ('partial', 'done', 'partial_closed'):
            await catat(pg, w, rid, 2 if name == 'done' else 1)
        if name in ('rejected', 'closed', 'partial_closed'):
            async with pg() as db:
                await barang.keputusan(db, user=await db.get(User, w['user']), rid=rid,
                    aksi='tolak' if name == 'rejected' else 'tutup-sisa',
                    alasan='Keputusan fixture ' + name)
    return dict(w=w, ids=ids, source=sid)


def scope(page, value):
    return page.locator(f'#pk-request-stats [data-status-permintaan="{value}"]')


async def counts(page, active, closed, total):
    for value, n in [('aktif', active), ('selesai_ditutup', closed), ('', total)]:
        await expect(scope(page, value).locator('strong')).to_have_text(str(n))
    await expect(page.locator('#pk-jumlah-permintaan')).to_have_text(str(active))


async def rows(page, n):
    await expect(page.locator('#pk-daftar .riwayat-list article')).to_have_count(n)
    await expect(page.locator('#pk-daftar .riwayat-desktop-row')).to_have_count(n)


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('role,warehouse,look,origin,admin', [
    ('admin', None, None, True, True), ('superadmin', None, None, True, True),
    ('operator', 'Gudang 2', None, True, False),
    ('operator', 'Gudang 1', None, False, False),
    ('admin', None, 'operator:g2', True, False),
    ('superadmin', None, 'operator:g1', False, False),
])
async def test_kelompok_aksi_dan_next_step_sesuai_peran(pg, campuran, width, role, warehouse, look, origin, admin):
    x = campuran
    async with browser_app(pg, peran=role, gudang=warehouse, width=width) as (page, client, _):
        if look:
            from app.web.lihat_sebagai import NAMA_KUKI
            client.cookies.set(NAMA_KUKI, look)
            await page.context.add_cookies([dict(name=NAMA_KUKI, value=look, url=BASE)])
        before = await fakta(pg)
        posts = catat_post(page)
        await page.goto(BASE + '/transfer-bertahap')
        await expect(scope(page, 'aktif')).to_have_attribute('aria-pressed', 'true')
        await counts(page, 3, 4, 7)
        await rows(page, 3)
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Sisa ditutup')
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Ditolak')
        await expect(page.locator('#pk-daftar')).to_contain_text('Perintah PTR-')
        await expect(page.locator('#pk-daftar')).to_contain_text(
            'Periksa jumlah dan tujuan' if admin else 'Menunggu Admin memeriksa permintaan')
        await expect(page.locator('#pk-daftar [data-catatan]:visible')).to_have_count(3 if admin else 2 if origin else 0)
        await expect(page.locator('#pk-daftar')).to_contain_text(
            'Catat jumlah aktual' if origin else 'Menunggu operator gudang asal')
        await scope(page, 'selesai_ditutup').focus()
        await page.keyboard.press('Enter')
        await expect(scope(page, 'selesai_ditutup')).to_be_focused()
        await rows(page, 4)
        await counts(page, 3, 4, 7)
        await expect(page.locator('#pk-daftar')).to_contain_text('Sisa ditutup')
        await expect(page.locator('#pk-daftar')).to_contain_text('Ditolak')
        await expect(page.locator('#pk-daftar [data-catatan]:visible')).to_have_count(0)
        await expect(page.locator('#pk-daftar')).to_contain_text('Tidak ada pelaksanaan lanjutan')
        await scope(page, '').click()
        await rows(page, 7)
        await expect(scope(page, '')).to_be_focused()
        assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        if width == 1440:
            assert await page.locator('#pk-daftar .tp-request-grid>span').evaluate_all(
                'cells=>cells.every(c=>c.scrollWidth<=c.clientWidth+2)')
        out = os.environ.get('UJI_TRANSFER_AKTIF_PREVIEW')
        if out and role == 'admin' and not look:
            await scope(page, 'aktif').click()
            Path(out).mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(Path(out) / f'permintaan-aktif-admin-{width}.png'), full_page=True)
        assert posts == []
        assert await fakta(pg) == before


async def test_pencarian_filter_url_lama_dan_detail_terminal_tetap_tersedia(pg, campuran):
    x = campuran
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        payload = (await client.get('/api/transfer-bertahap')).json()
        rejected = next(r for r in payload['permintaan'] if r['id'] == -x['ids']['rejected'])
        await page.goto(BASE + '/transfer-bertahap')
        await expect(scope(page, 'aktif')).to_have_attribute('aria-pressed', 'true')
        await page.locator('#pk-filter-buka').click()
        await page.locator('#pk-filter [name=jenis]').select_option('barang')
        await page.locator('#pk-filter [name=asal]').select_option(str(x['w']['wh']))
        await page.get_by_role('button', name='Terapkan filter', exact=True).click()
        await page.locator('#pk-cari').fill(rejected['nomor'])
        await expect(page.locator('#pk-daftar .tp-kosong')).to_be_visible()
        await counts(page, 3, 4, 7)
        await page.get_by_role('button', name='Lihat selesai & ditutup', exact=True).click()
        await rows(page, 1)
        await expect(page.locator('#pk-cari')).to_have_value(rejected['nomor'])
        await expect(page).to_have_url(re.compile(r'asal=.*jenis=barang.*cari='))
        await page.reload()
        await rows(page, 1)
        await expect(scope(page, 'selesai_ditutup')).to_have_attribute('aria-pressed', 'true')
        await page.goto(BASE + '/transfer-bertahap?status=')
        await rows(page, 7)
        await expect(scope(page, '')).to_have_attribute('aria-pressed', 'true')
        await page.goto(BASE + '/transfer-bertahap?status=selesai')
        await rows(page, 1)
        await expect(page.locator('#pk-daftar')).to_contain_text('Selesai')
        await page.goto(BASE + '/transfer-bertahap?permintaan=' + str(rejected['id']))
        await expect(page.locator('#pk-detail')).to_contain_text('Keputusan fixture rejected')
        await page.get_by_role('button', name='Tutup detail', exact=True).click()
        await rows(page, 3)
        await page.locator('[data-pk-tab=riwayat]').click()
        await expect(page.locator('#pk-ringkasan')).to_contain_text('Semua status')
        await expect(page.locator('#pk-jalan')).to_contain_text('2 karung')


async def test_empty_aktif_tidak_menyembunyikan_keputusan_dan_tidak_menulis(pg, campuran):
    x = campuran
    for name in ('pending', 'ready', 'partial'):
        async with pg() as db:
            await barang.keputusan(db, user=await db.get(User, x['w']['user']), rid=x['ids'][name],
                aksi='tolak' if name == 'pending' else 'tutup-sisa', alasan='Semua kebutuhan fixture sudah ditutup')
    async with browser_app(pg, gudang='Gudang 1') as (page, _, _):
        before = await fakta(pg)
        await page.goto(BASE + '/transfer-bertahap')
        await counts(page, 0, 7, 7)
        await expect(page.locator('#pk-daftar')).to_contain_text('Tidak ada permintaan aktif')
        await page.get_by_role('button', name='Lihat selesai & ditutup', exact=True).click()
        await rows(page, 7)
        await expect(page.locator('#pk-daftar [data-catatan]:visible')).to_have_count(0)
        assert await fakta(pg) == before


async def test_refresh_counter_ditahan_sampai_fokus_selesai_dan_filter_tetap(pg, campuran):
    x = campuran
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap?status=aktif&jenis=barang&cari=Baris')
        await rows(page, 3)
        state = await snapshot(page, client)
        posts = catat_post(page)
        await scope(page, 'aktif').focus()
        async with pg() as db:
            await barang.keputusan(db, user=await db.get(User, x['w']['user']), rid=x['ids']['pending'], aksi='tolak', alasan='Selesai ditinjau saat pembacaan baru')
        state.payload = (await client.get('/api/transfer-bertahap')).json()
        await state.baca(page)
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status', 'tertunda')
        await counts(page, 3, 4, 7)
        await expect(scope(page, 'aktif')).to_be_focused()
        await page.locator('#pk-filter-buka').focus()
        await counts(page, 2, 5, 7)
        await rows(page, 2)
        await expect(page.locator('#pk-cari')).to_have_value('Baris')
        await expect(page).to_have_url(re.compile(r'status=aktif.*jenis=barang.*cari=Baris'))
        assert posts == []


async def test_dibuka_kembali_berpindah_ke_aktif_setelah_refresh_tanpa_mereset_filter(pg, campuran):
    from app.services import koreksi_transfer_barang as koreksi
    x = campuran
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        await page.goto(BASE + '/transfer-bertahap?status=selesai_ditutup')
        await rows(page, 4)
        state = await snapshot(page, client)
        posts = catat_post(page)
        req = dict(aksi='buka', berat_kg=None, tujuan=None, alasan='Kebutuhan fixture dilanjutkan', kunci=uuid.uuid4().hex)
        async with pg() as db:
            user = await db.get(User, x['w']['user'])
            pre = await koreksi.periksa(db, jenis='permintaan', ident=x['ids']['closed'], user=user, req=req)
        req.update(pemeriksaan=pre['pemeriksaan'], konfirmasi=True)
        async with pg() as db:
            await koreksi.simpan(db, jenis='permintaan', ident=x['ids']['closed'], user=await db.get(User, x['w']['user']), req=req)
        state.payload = (await client.get('/api/transfer-bertahap')).json()
        await state.baca(page)
        await counts(page, 4, 3, 7)
        await rows(page, 3)
        await expect(scope(page, 'selesai_ditutup')).to_have_attribute('aria-pressed', 'true')
        await scope(page, 'aktif').click()
        await rows(page, 4)
        reopened = next(r for r in state.payload['permintaan'] if r['id'] == -x['ids']['closed'])
        await expect(page.locator('#pk-daftar')).to_contain_text(reopened['nomor'])
        assert posts == []


@pytest.mark.parametrize('role,gudang', [('admin', None), ('operator', 'Gudang 1'), ('operator', 'Gudang 2')])
@pytest.mark.parametrize('width', [390, 1440])
async def test_pk_sisa_nol_perjalanan_belum_selesai_tetap_aktif(pg, siap, role, gudang, width):
    await buat(pg, siap, '6000')  # Kontrak perjalanan historis, hanya fixture lokal.
    async with browser_app(pg, peran=role, gudang=gudang, width=width) as (page, client, _):
        before = await fakta(pg)
        r = (await client.get('/api/transfer-bertahap')).json()['permintaan'][0]
        assert r['status'] == 'dikirim' and float(r['sisa']) == 0 and float(r['perjalanan_kg']) == 6000
        await page.goto(BASE + '/transfer-bertahap')
        await counts(page, 1, 0, 1)
        await rows(page, 1)
        await expect(page.locator('#pk-daftar')).to_contain_text('Perjalanan belum selesai')
        await expect(page.locator('#pk-daftar')).not_to_contain_text('Dipindahkan sebagian')
        await expect(page.locator('#pk-daftar [data-catatan]:visible')).to_have_count(0)
        await page.goto(BASE + '/transfer-bertahap?status=perlu_transfer')
        await rows(page, 1)  # URL lama tetap membaca dokumen berjalan yang sama.
        assert await fakta(pg) == before


async def test_count_mencakup_lebih_dari_100_permintaan_dan_tetap_bercakupan(pg, lokasi):
    from app.models import Warehouse
    from hmu_core.organisasi import PenempatanGudang
    w = lokasi
    async with pg() as db:
        factory = await db.scalar(select(FinishedGoodsStock).where(
            FinishedGoodsStock.warehouse_id == w['wh'], FinishedGoodsStock.jasa_id.is_(None)))
        sid = factory.id
        fields = {c.name: getattr(factory, c.name) for c in factory.__table__.columns if c.name not in ('id', 'created_at', 'updated_at')}
        placement = await db.scalar(select(PenempatanGudang).where(PenempatanGudang.warehouse_id == w['wh']))
        others = [Warehouse(nama_gudang='Gudang fixture lain ' + str(i), aktif=True) for i in range(2)]
        db.add_all(others); await db.flush()
        db.add_all([PenempatanGudang(warehouse_id=g.id, company_id=placement.company_id, lokasi_pabrik_id=placement.lokasi_pabrik_id) for g in others])
        fields['warehouse_id'] = others[0].id
        hidden = FinishedGoodsStock(**fields); db.add(hidden); await db.commit()
        hidden_id, hidden_target = hidden.id, others[1].id
    for _ in range(103):
        await minta(pg, w, 'barang', sid, 1)
    await minta(pg, w, 'barang', hidden_id, 1, target=hidden_target)
    async with browser_app(pg, gudang='Gudang 1', width=1440) as (page, client, _):
        payload = (await client.get('/api/transfer-bertahap')).json()
        assert len(payload['permintaan']) == 103
        assert all(r['asal_id'] == w['wh'] and r['tujuan_id'] == w['target'] for r in payload['permintaan'])
        await page.goto(BASE + '/transfer-bertahap')
        await counts(page, 103, 0, 103)
        await rows(page, 103)
        await page.locator('#pk-cari').fill(payload['permintaan'][-1]['nomor'])
        await rows(page, 1)
        await counts(page, 103, 0, 103)


async def test_menunggu_admin_stok_nol_tetap_aktif_tanpa_tombol_persetujuan(pg, lokasi):
    w = lokasi
    pending = await minta(pg, w, 'barang', w['source'], 1)
    moving = await minta(pg, w, 'barang', w['source'], 100)
    await approve(pg, w, moving, 100)
    await catat(pg, w, moving, 100)
    async with browser_app(pg, peran='admin', gudang=None) as (page, client, _):
        payload = (await client.get('/api/transfer-bertahap')).json()
        request = next(r for r in payload['permintaan'] if r['id'] == -pending)
        assert request['status'] == 'diminta' and float(request['bebas']) == 0
        await page.goto(BASE + '/transfer-bertahap')
        await counts(page, 1, 1, 2)
        await rows(page, 1)
        await expect(page.locator('#pk-daftar')).to_contain_text('Periksa ketersediaan sumber')
        await expect(page.locator('#pk-daftar [data-catatan]:visible')).to_have_count(0)
        await page.locator('#pk-daftar [data-detail]:visible').first.click()
        await expect(page.locator('#pk-detail')).to_contain_text('Tolak permintaan')
