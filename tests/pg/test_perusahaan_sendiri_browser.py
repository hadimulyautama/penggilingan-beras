import os
import pytest
from pathlib import Path
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_master_organisasi import organisasi
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_perusahaan_sendiri import pasang,bisnis,BASE
from tests.pg.test_pengaturan_organisasi import fakta
from tests.pg.test_pengaturan_organisasi_browser import browser_http
from tests.pg.test_riwayat_giling import _klien

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi,pytest.mark.skipif(os.getenv('UJI_BROWSER_ORGANISASI')!='1',reason='Profil browser eksplisit')]


@pytest.mark.parametrize('width',[320,390,1440])
async def test_admin_perusahaan_menambah_lokasi_dan_gudang_dari_pengaturan(pg,organisasi,running,width,tmp_path):
    async with await _klien(pg,peran=P.ADMIN) as c:
        await pasang(pg,c,organisasi);before=await fakta(pg)
        async with browser_http(c,width) as (page,base):
            await page.goto(base+'/pengaturan')
            await page.get_by_role('link',name='Perusahaan saya',exact=False).click()
            await expect(page.locator('.org h1')).to_have_text('Perusahaan uji')
            box=page.locator('details').filter(has=page.get_by_text('Tambah lokasi perusahaan',exact=True))
            await box.locator('summary').click()
            await box.get_by_label('Nama lokasi',exact=True).fill('Pabrik cabang uji')
            await box.get_by_label('Kode lokasi',exact=True).fill('cabang-'+str(width))
            await box.get_by_label('Alamat',exact=True).fill('Alamat uji yang bukan data produksi')
            await box.get_by_label('Alasan perubahan').fill('Penambahan lokasi melalui aplikasi perusahaan')
            await box.get_by_role('button',name='Simpan',exact=True).click()
            await expect(page.locator('[role=status]')).to_contain_text('Perubahan tersimpan')
            card=page.locator('section.kartu').filter(has=page.get_by_role('heading',name='Pabrik cabang uji',exact=True))
            await card.get_by_text('Tambah gudang pada lokasi ini',exact=True).click()
            box=card.locator('details').filter(has=page.get_by_text('Tambah gudang pada lokasi ini',exact=True))
            await box.get_by_label('Nama gudang',exact=True).fill('Gudang cabang uji')
            await box.get_by_label('Alasan perubahan').fill('Penambahan gudang pada lokasi cabang')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await box.get_by_role('button',name='Simpan',exact=True).click()
            await expect(page.locator('.org')).to_contain_text('Gudang cabang uji')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            out=Path(os.getenv('BUKTI_ORGANISASI',str(tmp_path)));out.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(out/f'perusahaan-sendiri-{width}.png'),full_page=True)
        assert bisnis(await fakta(pg))==bisnis(before)
