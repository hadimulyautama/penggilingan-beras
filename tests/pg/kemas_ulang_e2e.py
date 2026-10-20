"""Uji browser eksplisit (memerlukan Playwright dari lingkungan tampilan).

Jalankan berkas ini secara eksplisit dengan UJI_PG_URL pada database uji.
Suite server standar tidak memasang browser; uji ini tidak dilewati diam-diam.
"""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import User,FinishedGoodsStock,KemasUlang
from tests.pg.test_kemas_ulang import awal
from tests.pg.test_stok_produk_jasa import sosoh_jasa
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('jasa',[False,True])
@pytest.mark.parametrize('terang',[False,True])
async def test_browser_halaman_utuh_simpan_dan_kembali(pg,sosoh_jasa,jasa,terang,tmp_path):
    """JS asli + sesi/CSRF asli + HTTP aplikasi + stok PostgreSQL terisolasi."""
    from tests.pg.test_barang_keluar import _klien
    from hmu_identitas.peran import SUPERADMIN
    from playwright.sync_api import sync_playwright,expect
    from urllib.parse import urlsplit
    import re
    req,sku,std=await awal(pg,sosoh_jasa,jasa)
    async with pg() as db:
        u=await db.get(User,sosoh_jasa['user']);u.role=SUPERADMIN;await db.commit()
    c=await _klien(pg,sosoh_jasa['user'],'browser372')
    c.cookies.set('produksi_terik','1' if terang else '0')
    loop=asyncio.get_running_loop()
    async def jawab(path,method,headers,body):
        return await c.request(method,path,headers=headers,content=body)
    def browser():
        with sync_playwright() as p:
            b=p.chromium.launch();context=b.new_context(viewport={'width':390,'height':844},service_workers='block')
            context.add_cookies([{'name':k,'value':v,'url':'http://uji.local/'} for k,v in c.cookies.items()])
            page=context.new_page();posts=[];dialog=[]
            def route(r):
                u=urlsplit(r.request.url);path=u.path+('?' +u.query if u.query else '')
                if u.path=='/api/aliran':r.fulfill(body='',content_type='text/event-stream');return
                if r.request.method=='POST' and u.path=='/api/kemas-ulang':posts.append(path)
                response=asyncio.run_coroutine_threadsafe(jawab(path,r.request.method,r.request.headers,r.request.post_data_buffer),loop).result(timeout=30)
                r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
            page.route('**/*',route)
            page.on('dialog',lambda d:(dialog.append(d.type),d.dismiss()))
            url=f'http://uji.local/stok-produk/kemas-ulang?sku_id={sku}&std_id={std}'+(f'&jasa_id={sosoh_jasa["jasa_id"]}' if jasa else '')
            page.goto(url)
            page.locator('[name=sumber_id]').select_option(str(req['sumber_id']))
            page.locator('[name=jumlah_asal]').fill('4')
            assert page.locator('[name=kemasan] option[value="laminasi|25"]').count()==0
            page.locator('[name=kemasan]').select_option('biasa|40')
            page.locator('[name=jumlah_baru]').fill('2')
            expect(page.locator('[data-saldo-kemasan]')).to_contain_text('100 lembar')
            assert page.locator('[name=merk] option').all_text_contents()==['Pilih merek','Tanpa merek · 100 lembar']
            assert posts==[]
            page.screenshot(path=tmp_path/f'pilihan-tersedia-{jasa}-{terang}.png')
            page.locator('[data-kemas-ulang] > a:visible').click()
            assert dialog==['beforeunload']
            assert page.locator('[name=jumlah_asal]').input_value()=='4'
            page.locator('[name=kemasan]').select_option('biasa|40')
            page.locator('[name=jumlah_baru]').fill('2')
            expect(page.locator('[data-saldo-kemasan]')).to_contain_text('100 lembar')
            page.locator('[name=setuju]').check();page.get_by_role('button',name='Catat kemas ulang',exact=True).click()
            page.wait_for_url(re.compile(r'/stok-produk(?:-jasa)?/detail\?'))
            assert ('/stok-produk-jasa/detail' in page.url)==jasa
            assert 'jenis=' in page.url
            if jasa:assert 'pelanggan_id=' in page.url
            expect(page.locator('#kabar')).to_contain_text('Kemas ulang berhasil. Stok sudah diperbarui.')
            expect(page.locator('#kabar')).to_be_visible()
            assert len(posts)==1
            page.screenshot(path=tmp_path/f'hasil-{jasa}-{terang}.png')
            page.reload()
            expect(page.locator('#kabar')).not_to_be_visible()
            assert dialog==['beforeunload'], 'simpan berhasil tidak boleh memunculkan peringatan kehilangan isian'
            baris=page.locator('tr').filter(has=page.locator('[data-kemas-curah]')).first
            expect(baris).to_contain_text('4.800 kg' if jasa else '8.800 kg')
            baris.locator('summary').click()
            assert baris.locator('summary').bounding_box()['height']>=48
            page.screenshot(path=tmp_path/f'aksi-stok-{jasa}-{terang}.png')
            page.locator('[data-kemas-curah]').first.click()
            expect(page.locator('#lembar')).to_be_visible()
            expect(page.locator('#f_sumber option')).not_to_have_count(1)
            pilihan=page.locator('#f_sumber option').all_text_contents()
            kode=sosoh_jasa['kode_jasa'] if jasa else sosoh_jasa['kode_pabrik']
            nilai=page.locator('#f_sumber option').evaluate_all('(xs)=>xs.map(x=>x.value).filter(Boolean)')
            assert nilai==[kode+'|medium'], (nilai,pilihan)
            assert len(pilihan)==2, pilihan
            assert len(posts)==1, 'membuka formulir kemas tidak boleh menyimpan stok'
            page.screenshot(path=tmp_path/f'kemas-curah-{jasa}-{terang}.png')
            page.set_viewport_size({'width':1440,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=tmp_path/f'kemas-curah-desktop-{jasa}-{terang}.png')

            b.close()
    async with c:
        await asyncio.to_thread(browser)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(KemasUlang))==1
        rows=list((await db.execute(select(FinishedGoodsStock))).scalars())
        assert sum(Decimal(str(r.berat_total_kg)) for r in rows)==200
        assert all(r.jasa_id==(sosoh_jasa['jasa_id'] if jasa else None) for r in rows)
