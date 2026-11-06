"""Alat sibuk adalah kondisi operasional; pembaca tidak menulis transaksi."""
import os
import pytest
from sqlalchemy import select
from tests.pg.test_giling_beberapa_silo import silos, _mulai
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_form_kadar_air import post
from tests.pg.test_form_pindah_silo import fakta
from app.services.seed import seed_master

pytestmark = pytest.mark.asyncio


async def test_sosoh_sibuk_juga_mengembalikan_kode_bukan_gagal_memuat(pg):
    from tests.pg.test_fasilitas import dunia
    from app.models import LiniProduksi, JenisProsesProduksi, PolishingProcess
    from app.database import now_local
    _, _, ops = await dunia(pg)
    async with pg() as db:
        line = await db.scalar(select(LiniProduksi).join(JenisProsesProduksi).where(JenisProsesProduksi.kode=='penyosohan'))
        lid = line.id
        db.add(PolishingProcess(kode_proses='POL-ALAT-SIBUK', status='proses', waktu_mulai=now_local(), created_by=ops[1].id, lini_produksi_id=lid))
        await db.commit()
    async with await _klien(pg, peran='operator', gudang='Gudang 2') as c:
        for path in ['silo-bahan-g2', 'ringkasan-mulai-penyosohan']:
            response = await c.get('/api/actions/'+path, params={'lini_id':lid})
            assert response.status_code == 409, response.text
            d = response.json()['detail']
            assert d['kode'] == 'alat_sedang_dipakai'
            assert d['proses'] == [{'kode':'POL-ALAT-SIBUK', 'href':'/proses-aktif/sosoh/POL-ALAT-SIBUK'}]


@pytest.mark.parametrize('lama', [False, True])
@pytest.mark.parametrize('peran', ['operator', 'admin', 'superadmin'])
async def test_kode_alat_sibuk_dan_penjaga_simpan(pg, silos, lama, peran):
    from app.models import MillingProcess
    await seed_master()
    r = await _mulai(pg, silos, ['A'])
    line = r.proc.lini_produksi_id
    if lama:
        async with pg() as db:
            p = await db.get(MillingProcess, r.proc.id)
            p.lini_produksi_id = None
            await db.commit()
    before = await fakta(pg)
    async with await _klien(pg, peran=peran, gudang='Gudang 1') as c:
        for path in ['silo-siap-giling', 'ringkasan-mulai-giling']:
            response = await c.get('/api/actions/'+path, params={'lini_id':line, 'silo':'B'})
            assert response.status_code == 409, response.text
            assert response.headers['cache-control'] == 'no-store'
            d = response.json()['detail']
            assert d['kode'] == 'alat_sedang_dipakai'
            assert d['alat']['id'] == line
            assert d['proses'] == [{'kode':r.proc.kode_proses, 'href':'/proses-aktif/giling/'+r.proc.kode_proses}]
            assert 'Selesaikan proses' in d['pesan']
        response = await post(c, 'mulai-giling', {'silo':'B', 'lini_id':line})
        assert response.status_code == 400 and r.proc.kode_proses in response.text
    assert await fakta(pg) == before
    async with await _klien(pg, peran='operator', gudang='Gudang 2') as c:
        response = await c.get('/api/actions/silo-siap-giling', params={'lini_id':line})
        assert response.status_code in (400, 403)
        assert r.proc.kode_proses not in response.text


@pytest.mark.skipif(os.getenv('UJI_BROWSER_PILIHAN_SILO') != '1', reason='Browser lokal opsional')
@pytest.mark.parametrize('width', [390, 1440])
async def test_panel_sibuk_pulih_otomatis_tanpa_pesan_jaringan(pg, silos, width):
    from playwright.async_api import expect
    from tests.pg.test_pengeringan_desain_browser import browser
    from tests.pg.skenario_silo import pastikan_silo_kosong
    from app.models import User
    from app.penggilingan.gudang1.services.milling import finish_milling
    await seed_master()
    r = await _mulai(pg, silos, ['A'])
    before = await fakta(pg)
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        async with browser(c, width) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            panel = page.locator('[data-status-alat]')
            await expect(panel).to_contain_text(r.proc.kode_proses)
            await expect(panel).to_contain_text('Penggilingan 1 sedang dipakai')
            await expect(panel).to_contain_text('Selesaikan proses')
            await expect(panel.get_by_role('link')).to_have_attribute('href', '/proses-aktif/giling/'+r.proc.kode_proses)
            await expect(page.locator('#simpan')).to_be_disabled()
            await expect(page.locator('.mg-preview')).to_be_hidden()
            text = await page.locator('#b_silo').inner_text()
            assert 'dipulihkan' not in text and 'gagal' not in text
            assert await page.get_by_role('button', name='Muat ulang pilihan silo').count() == 0
            assert await fakta(pg) == before
            async with pg() as db:
                u = await db.get(User, silos['user'])
                await pastikan_silo_kosong(db, user=u, kode_proses=r.proc.kode_proses)
                await finish_milling(db, user=u, kode_proses=r.proc.kode_proses, berat_akhir=6500)
            await page.evaluate("window.dispatchEvent(new Event('online'))")
            await expect(panel).to_have_count(0)
            await expect(page.locator('#b_silo input[value=B]')).to_be_enabled()
            await page.locator('#b_silo input[value=B]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('6.000')
            await expect(page.locator('#simpan')).to_be_enabled()


@pytest.mark.skipif(os.getenv('UJI_BROWSER_PILIHAN_SILO') != '1', reason='Browser lokal opsional')
async def test_alat_dipakai_saat_form_terbuka_pilihan_tetap_utuh(pg, silos):
    from playwright.async_api import expect
    from tests.pg.test_pengeringan_desain_browser import browser
    await seed_master()
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        async with browser(c, 390) as page:
            await page.goto('https://uji/pekerjaan?buka=mulai_giling')
            await expect(page.locator('#b_silo input[type=checkbox]')).to_have_count(2)
            await page.locator('#b_silo input[value=B]').check()
            await expect(page.locator('#mg-bobot')).to_contain_text('6.000')
            r = await _mulai(pg, silos, ['A'])
            before = await fakta(pg)
            await page.locator('#simpan').click()
            await expect(page.locator('[data-status-alat]')).to_contain_text(r.proc.kode_proses)
            await expect(page.locator('#b_silo input[value=B]')).to_be_checked()
            await expect(page.locator('#b_silo input[value=B]')).to_be_disabled()
            await expect(page.locator('#simpan')).to_be_disabled()
            assert 'dipulihkan' not in await page.locator('#b_silo').inner_text()
            assert await fakta(pg) == before
