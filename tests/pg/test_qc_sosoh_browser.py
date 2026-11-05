"""Alur ponsel nyata; semua permintaan memakai app ASGI dan Postgres uji."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select, func

from app.models import PolishingProcess, PolishingOutputLog, SampelQcSosoh
from app.database import now_local
from tests.pg.test_qc_sosoh import dunia
from tests.pg.test_riwayat_sosoh import _klien
from tests.pg.formulir import cap_formulir
from hmu_identitas.peran import ADMIN, OPERATOR

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('UJI_BROWSER_QC')!='1', reason='Aktifkan UJI_BROWSER_QC untuk uji browser lokal')]

async def test_kartu_detail_sampel_lab_dan_riwayat_di_browser(pg,dunia):
    from playwright.async_api import async_playwright
    out=Path(__file__).resolve().parents[2]/'output'/'qc-sosoh-20261104'
    out.mkdir(parents=True,exist_ok=True)
    async with await _klien(pg,peran=ADMIN) as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            page=await browser.new_page(viewport={'width':1200,'height':950})
            await page.context.add_cookies([dict(name=k.name,value=k.value,url='https://uji') for k in c.cookies.jar])
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            permintaan_sampel=[]
            balasan_sampel=[]
            async def lewat_app(route):
                req=route.request
                u=urlsplit(req.url)
                if u.netloc!='uji':
                    await route.abort();return
                headers={k:v for k,v in req.headers.items() if k.lower() not in ('host','cookie','content-length')}
                r=await c.request(req.method,req.url,headers=headers,content=req.post_data_buffer)
                if u.path=='/api/actions/sampel-qc-sosoh' and req.method=='POST':
                    permintaan_sampel.append(req.post_data_json)
                    balasan_sampel.append((r.status_code,r.text))
                    if len(permintaan_sampel)==1:
                        # Server sudah menyimpan, tetapi balasannya putus di jaringan.
                        await route.abort();return
                await route.fulfill(status=r.status_code,body=r.content,
                    headers={k:v for k,v in r.headers.items() if k.lower() not in ('content-length','content-encoding','set-cookie')})
            await page.route('**/*',lewat_app)
            kode=dunia['proc'].kode_proses
            await page.goto('https://uji/pekerjaan?tab=tindakan&jenis=qc')
            card=page.locator('details.antrian-item').filter(has=page.locator('a[href$="#qc-sosoh"]'))
            assert await card.count()==1
            await card.locator('summary').click()
            await page.screenshot(path=str(out/'kartu-qc-desktop.png'),full_page=True)
            await card.get_by_role('link',name='Buka QC penyosohan').click()
            editor=page.locator('[data-qc-editor]')
            await editor.wait_for(state='visible')
            await page.get_by_role('button',name='Premium',exact=True).click()
            await editor.locator('[data-qc-galat]').filter(has_text='mencoba kembali').wait_for()
            await page.get_by_role('button',name='Premium',exact=True).click()
            await page.wait_for_timeout(700)
            assert len(balasan_sampel)==2 and balasan_sampel[-1][0]==200, (balasan_sampel,await editor.locator('[data-qc-galat]').inner_text())
            await editor.locator('[data-qc-identitas]').filter(has_text='Premium').wait_for()
            assert permintaan_sampel[0]['kunci_kiriman']==permintaan_sampel[1]['kunci_kiriman']
            async with pg() as db:
                assert await db.scalar(select(func.count()).select_from(SampelQcSosoh))==1
            # QC tidak boleh membuang draf hasil yang belum disimpan pada editor proses.
            await page.locator('[data-sr-tab="hasil"]').click()
            await page.locator('[data-kb-output="medium"] input').fill('5000')
            await page.locator('[data-sr-tab="qc"]').click()
            for nama,nilai in [('kadar_air','13,455'),('broken_persen','9,995'),('md','123,456'),
                               ('transparant','1,005'),('whiteness','45,678')]:
                await editor.locator('[name="'+nama+'"]').fill(nilai)
            assert await editor.locator('input[inputmode="decimal"]').count()==5
            assert await editor.locator('[name="menir_persen"],[name="gabah"],[name="merang"],[name="butir_kuning"]').count()==0
            await page.screenshot(path=str(out/'input-qc-desktop.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await editor.screenshot(path=str(out/'input-qc-ponsel.png'))
            r=await c.post('/api/actions/sampel-qc-sosoh',json={'kode_proses':kode,'jenis':'medium','kunci_kiriman':'berikutnya'})
            assert r.status_code==200,r.text
            await editor.get_by_role('button',name='Simpan hasil QC').click()
            await page.locator('[data-qc-sosoh]').filter(has_text='Kadar air 13,46%').wait_for()
            assert await page.locator('[data-kb-output="medium"] input').input_value()=='5000'
            await page.locator('[data-sr-tab="hasil"]').click()
            await page.locator('[data-kb-output="medium"] input').fill('')
            async with pg() as db:
                assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==0
                q=await db.scalar(select(SampelQcSosoh).where(SampelQcSosoh.jenis=='premium'))
                assert float(q.kadar_air)==13.46 and q.hasil_pada
                assert float(q.broken_persen)==10 and float(q.md)==123.46
                assert float(q.transparant)==1.01 and float(q.whiteness)==45.68
                p=await db.get(PolishingProcess,dunia['proc'].id)
                p.status,p.waktu_selesai='selesai',now_local()
                await db.commit()
            await page.goto('https://uji/pekerjaan?tab=tindakan&jenis=qc')
            assert await page.get_by_role('link',name='Buka QC penyosohan').count()==0
            await page.goto('https://uji/riwayat-sosoh/'+str(dunia['proc'].id))
            assert await page.locator('[data-qc-baru]').count()==0
            await page.locator('[data-qc-lengkapi]').click()
            assert await page.locator('[data-qc-editor]').is_visible()
            assert 'Medium' in await page.locator('[data-qc-identitas]').inner_text()
            await page.screenshot(path=str(out/'riwayat-qc-ponsel.png'),full_page=True)
            await page.goto('https://uji/pekerjaan?buka=qc_sosoh&nilai='+str(r.json()['sampel_id']))
            await page.locator('#f_md').wait_for(state='visible')
            for nama in ('kadar_air','broken_persen','md','transparant','whiteness'):
                bidang=page.locator('#f_'+nama)
                assert await bidang.get_attribute('inputmode')=='decimal'
                assert await bidang.get_attribute('data-angka') is None
            assert not errors,errors
            await browser.close()
