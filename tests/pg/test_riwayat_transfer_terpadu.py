"""Sumber riwayat tunggal: kelompok baru + lot lama tanpa menghitung ganda."""
import uuid
import pytest
from sqlalchemy import select, func
from app.models import User, InternalTransfer, PengirimanPkItem
from app.services import pengiriman_pk as s
from app.services.riwayat_transfer_terpadu import catatan_lama
from tests.pg.test_pengiriman_pk_bertahap import siap
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_riwayat_transfer import _klien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def campuran(pg, pabrik):
    from app.services import transfer, permintaan_pk as m
    from tests.pg.test_pengiriman_pk_bertahap import lot_lain
    w = pabrik
    async with pg() as db:
        from hmu_core.organisasi import Perusahaan,LokasiPabrik,PenempatanGudang
        company=Perusahaan(kode='RIWAYAT',nama='Perusahaan Riwayat');db.add(company);await db.flush()
        sites=[LokasiPabrik(company_id=company.id,kode='A',nama='Pabrik Asal'),LokasiPabrik(company_id=company.id,kode='B',nama='Pabrik Tujuan')]
        db.add_all(sites);await db.flush()
        a=await db.get(User,w['op1']);b=await db.get(User,w['op2'])
        db.add_all([PenempatanGudang(warehouse_id=a.default_warehouse_id,company_id=company.id,lokasi_pabrik_id=sites[0].id),PenempatanGudang(warehouse_id=b.default_warehouse_id,company_id=company.id,lokasi_pabrik_id=sites[1].id)])
        await db.commit()
    async with pg() as db:
        old = await transfer.create_internal_transfer(db,user=await db.get(User,w['op1']),
            kode_proses=w['lot'],lokasi_tujuan='ditumpuk',berat=1500)
        old_id = old.transfer.id
    async with pg() as db:
        r = await m.minta(db,user=await db.get(User,w['op2']),kode_proses=w['lot'],berat=4500)
        rid = r.id
    rid2 = await lot_lain(pg,w)
    async with pg() as db:
        await s.setujui_banyak(db,user=await db.get(User,w['admin']),items=[
            dict(permintaan_id=rid,berat_kg='4500',tujuan='ditumpuk'),
            dict(permintaan_id=rid2,berat_kg='1000',tujuan='ditumpuk')])
    async with pg() as db:
        new = await s.buat(db,user=await db.get(User,w['op1']),items=[
            dict(permintaan_id=rid,berat_kg='1000'),dict(permintaan_id=rid2,berat_kg='1000')],
            kunci=uuid.uuid4().hex,pakai_kendaraan=False)
    return dict(**w,old_id=old_id,new_id=new['id'])


async def test_total_kelompok_dan_catatan_lama_sama_dengan_buku_transfer(pg,campuran):
    from decimal import Decimal
    async with await _klien(pg,peran='admin') as c:
        data = (await c.get('/api/transfer-bertahap')).json()
    rows = data['pengiriman']
    assert len(rows) == 2
    assert sum(len(j['items']) for j in rows) == 3
    assert sum(Decimal(j.get('total_efektif',j['total'])) for j in rows) == 3500
    async with pg() as db:
        assert await db.scalar(select(func.sum(InternalTransfer.berat_kg))) == 3500
        assert await db.scalar(select(func.count()).select_from(InternalTransfer)) == 3


@pytest.mark.parametrize('width',[390,1440])
async def test_kartu_lama_dan_baru_satu_daftar_dengan_detail_yang_benar(pg,campuran,width):
    from playwright.async_api import expect
    from tests.pg.test_transfer_pk_halaman import browser_app, BASE
    async with browser_app(pg,peran='admin',gudang=None,width=width) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap?tab=riwayat')
        await expect(page.locator('#pk-jalan .riwayat-desktop-row')).to_have_count(3)
        await expect(page.locator('#pk-jalan .riwayat-list article')).to_have_count(3)
        await expect(page.locator('#pk-ringkasan')).to_contain_text('Semua status')
        await expect(page.locator('#pk-jalan')).to_contain_text('1.500 kg')
        await expect(page.locator('#pk-jalan')).to_contain_text('1.000 kg')
        surface = '.riwayat-list' if width<900 else '.riwayat-desktop-list'
        link = page.locator(f'#pk-jalan {surface} a[href="/riwayat-transfer/{campuran["old_id"]}"]').first
        await expect(link).to_be_visible()
        await expect(page.locator('#pk-history-stats')).to_contain_text('3.500 kg')
        header=page.locator('#pk-jalan .riwayat-desktop-head')
        assert await header.locator('span').all_text_contents()==['Kode transfer / waktu','Nama pemilik','Barang / lot asal','Asal','Tujuan','Jumlah','Status transfer']
        desktop=page.locator('#pk-jalan .riwayat-desktop-row').first.locator('summary>span')
        await expect(desktop.nth(3)).to_contain_text('Pabrik Asal')
        await expect(desktop.nth(4)).to_contain_text('Pabrik Tujuan')
        await expect(desktop.nth(4)).to_contain_text('Tumpukan')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=f'/private/tmp/transfer-riwayat-{width}.png',full_page=True)
        await link.click()
        await expect(page.locator('.desktop-back')).to_have_attribute('href','/transfer-bertahap?tab=riwayat')


async def test_kelompok_baru_tidak_muncul_lagi_sebagai_catatan_lama(pg, siap):
    w = siap
    async with pg() as db:
        await s.buat(db, user=await db.get(User, w['op1']),
                     items=[dict(permintaan_id=w['rid'], berat_kg='1000')],
                     kunci=uuid.uuid4().hex, pakai_kendaraan=False)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(InternalTransfer)) == 1
        assert await catatan_lama(db, user=await db.get(User, w['admin'])) == []
        # Simulasikan catatan historis yang belum mempunyai pengelompokan.
        item = await db.scalar(select(PengirimanPkItem))
        item.internal_transfer_id = None
        await db.commit()
    async with pg() as db:
        rows = await catatan_lama(db, user=await db.get(User, w['admin']))
        assert len(rows) == 1 and rows[0]['total_efektif'] == '1000.00'
        assert rows[0]['nomor'].startswith('TRF-') and rows[0]['detail_url'].startswith('/riwayat-transfer/')


async def test_alamat_riwayat_lama_menuju_satu_halaman_dan_detail_tetap_terbuka(pg, siap):
    w = siap
    async with pg() as db:
        await s.buat(db, user=await db.get(User,w['op1']),
                     items=[dict(permintaan_id=w['rid'],berat_kg='1000')],
                     kunci=uuid.uuid4().hex,pakai_kendaraan=False)
        tid = await db.scalar(select(InternalTransfer.id))
    async with await _klien(pg, peran='admin') as c:
        for path in ['/riwayat-transfer', '/riwayat?tab=proses&jenis=transfer']:
            r = await c.get(path, follow_redirects=False)
            assert r.status_code == 303 and r.headers['location'] == '/transfer-bertahap?tab=riwayat'
        r = await c.get(f'/riwayat-transfer/{tid}')
        assert r.status_code == 200
        assert 'href="/transfer-bertahap?tab=riwayat"' in r.text
        assert 'aria-label="Jenis proses"' not in r.text
