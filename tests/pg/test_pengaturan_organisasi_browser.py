"""Browser nyata: pintu Pengaturan, master, dan pratinjau tanpa mutasi stok."""
import os,re,asyncio
from contextlib import asynccontextmanager
import uvicorn
from pathlib import Path
import pytest
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta,tanpa_master
from tests.profil_browser import mesin,konteks
from app.main import app

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi,
 pytest.mark.skipif(os.getenv('UJI_BROWSER_ORGANISASI')!='1',reason='Profil browser organisasi harus dipilih eksplisit')]


@asynccontextmanager
async def browser_http(c,width):
    # Lifespan dimatikan: hanya HTTP pada fixture database uji yang dipakai;
    # tidak menyalakan bot, scheduler, seed, atau integrasi latar aplikasi.
    from playwright.async_api import async_playwright
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,lifespan='off',log_level='error'))
    task=asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if task.done():task.result()
            if server.started:break
            await asyncio.sleep(.01)
        assert server.started
        port=server.servers[0].sockets[0].getsockname()[1];base=f'http://127.0.0.1:{port}'
        async with async_playwright() as pw:
            b=await mesin(pw).launch()
            context=await b.new_context(**konteks(pw,width,1000),service_workers='block')
            await context.add_cookies([dict(name=k.name,value=k.value,url=base) for k in c.cookies.jar])
            page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            await page.route('**/api/aliran*',lambda r:r.abort())
            await page.route('https://**/*',lambda r:r.abort())
            try:yield page,base
            finally:await b.close()
            assert not errors,errors
    finally:
        server.should_exit=True
        await asyncio.wait_for(task,timeout=10)


@pytest.mark.parametrize('width',[320,390,1440])
async def test_pengaturan_sampai_pratinjau_tetap_terbaca_dan_transaksi_identik(pg,running,width,tmp_path):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        before=await fakta(pg)
        async with browser_http(c,width) as (page,base):
            await page.goto(base+'/pengaturan')
            await page.get_by_role('link',name='Perusahaan & lokasi pabrik',exact=False).click()
            await expect(page.locator('#org-judul')).to_have_text('Perusahaan & lokasi pabrik')
            await page.get_by_text('Tambah perusahaan',exact=True).click()
            await page.get_by_label('Nama perusahaan',exact=True).fill('Perusahaan uji panjang untuk ponsel')
            await page.get_by_label('Kode perusahaan',exact=True).fill('contoh-'+str(width))
            await page.get_by_label('Alasan penambahan',exact=True).fill('Menyiapkan master melalui aplikasi')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await page.get_by_role('button',name='Tambahkan perusahaan',exact=True).click()
            await expect(page).to_have_url(re.compile(r'/organisasi/perusahaan/\d+\?tersimpan=1'))
            await page.get_by_text('Tambah lokasi pabrik',exact=True).click()
            await page.get_by_label('Nama lokasi pabrik',exact=True).fill('Pabrik Utara')
            await page.get_by_label('Kode lokasi pabrik',exact=True).fill('utara')
            await page.get_by_label('Alamat lokasi pabrik',exact=True).fill('Alamat lokasi pengujian')
            # Formulir ubah perusahaan juga ada, tetapi masih tertutup.
            add=page.locator('form[action$="/lokasi/baru"]')
            await add.get_by_label('Alasan penambahan',exact=True).fill('Mendaftarkan lokasi yang akan ditinjau')
            await page.get_by_role('button',name='Tambahkan lokasi pabrik',exact=True).click()
            await expect(page).to_have_url(re.compile(r'/organisasi/lokasi/\d+\?tersimpan=1'))
            await expect(page.get_by_label('Kode lokasi pabrik',exact=True)).to_have_attribute('readonly','')
            await page.get_by_role('link',name='Siapkan pratinjau penetapan',exact=True).click()
            await page.locator('input[name=warehouse_id]').first.check()
            await page.get_by_role('button',name='Pratinjau penetapan',exact=True).click()
            await expect(page.locator('[data-rencana-penetapan]')).to_be_visible()
            await expect(page.locator('[data-rencana-penetapan]')).to_contain_text('Belum ada penetapan yang disimpan')
            assert await page.locator('.org form[method=post]').count()==0
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            out=Path(os.getenv('BUKTI_ORGANISASI',str(tmp_path)));out.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(out/f'pratinjau-{width}.png'),full_page=True)
        assert tanpa_master(await fakta(pg))==tanpa_master(before)
