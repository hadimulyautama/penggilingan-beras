"""Respons hilang setelah commit: formulir mengulang kiriman yang sama sekali saja."""
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import User,PolishingOutputLog,BrokenKeSilo,HasilSampingKeSilo
from tests.pg.test_form_menir_silo import menir,sosoh
from tests.pg.test_barang_keluar import _klien
from tests.pg.test_pengeringan_desain_browser import browser

@pytest.mark.parametrize('jenis',['broken','menir','reject'])
@pytest.mark.parametrize('role,width',[('operator',390),('superadmin',1440)])
async def test_jawaban_putus_setelah_commit_ulangi_tetap_satu_mutasi(pg,menir,jenis,role,width):
    from playwright.async_api import expect
    async with pg() as db:
        u=await db.get(User,menir['user']);u.role=role
        if jenis=='broken':
            db.add(PolishingOutputLog(polishing_process_id=menir['proc_id'],jenis='broken',berat_kg=100,waktu_update=now_local(),input_by=u.id))
        await db.commit()
    async with await _klien(pg,menir['user'],'uji-browser-kiriman',mode='operator' if role=='operator' else 'admin') as c:
        async with browser(c,width) as page:
            await page.emulate_media(reduced_motion='reduce')
            kiriman=[]
            async def putus(r):
                req=r.request
                kiriman.append(req.post_data_json)
                headers={k:v for k,v in req.headers.items() if k.lower() not in ('host','cookie','content-length')}
                result=await c.request(req.method,req.url,headers=headers,content=req.post_data_buffer)
                assert result.status_code==200,result.text
                if len(kiriman)==1:
                    await r.abort('failed') # Server sudah commit, jawaban tak sampai ke ponsel.
                else:
                    await r.fulfill(status=result.status_code,body=result.content,
                        headers={'content-type':'application/json'})
            await page.route('**/api/actions/masukkan-'+jenis+'-silo',putus)
            await page.goto('https://uji/stok-produk/detail?jenis='+jenis+'&gudang=g2&buka=masukkan_'+jenis+'_silo')
            await page.locator('#f_berat_kg').wait_for(state='visible')
            field='proses' if jenis=='broken' else 'pemilik'
            value='pemilik|pabrik' if jenis=='broken' else 'pabrik'
            await page.locator('#f_'+field+' option[value="'+value+'"]').wait_for(state='attached')
            await page.locator('#f_'+field).select_option(value)
            await page.locator('#f_silo option[value="Campuran Timur"]').wait_for(state='attached')
            await page.locator('#f_silo').select_option('Campuran Timur')
            await page.locator('#f_berat_kg').fill('75')
            await page.locator('#simpan').click()
            retry=page.locator('#ulang-kiriman-silo')
            await expect(retry).to_be_visible()
            await expect(page.locator('#f_berat_kg')).to_have_value('75')
            await expect(page.locator('#lembar .grup')).to_have_attribute('inert','')
            assert len(kiriman)==1 # Tidak ada retry POST otomatis.
            await retry.click()
            await page.locator('#lembar').wait_for(state='hidden')
            assert len(kiriman)==2 and kiriman[0]==kiriman[1]
            assert len(kiriman[0]['kunci_kiriman'])>=16
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
    async with pg() as db:
        model=BrokenKeSilo if jenis=='broken' else HasilSampingKeSilo
        assert await db.scalar(select(func.sum(model.berat_kg)))==75
