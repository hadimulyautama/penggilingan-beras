"""Owner fixture proof: native document shells and sameURL read-only hydration."""
import asyncio
from pathlib import Path
import os
import re

import pytest
from bs4 import BeautifulSoup
from fastapi import HTTPException
from playwright.async_api import expect

from tests.pg.test_konsolidasi_stok import stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE
from app.web.riwayat_daftar_metadata import PROCESS, QC, metadata

pytestmark=pytest.mark.asyncio
PATHS=tuple(PROCESS)+tuple('/riwayat-qc/'+q for q in sorted(QC))
HEADERS={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}


def allowed(role,warehouse,path):
    return role=='admin' or (path in ('/riwayat-sosoh','/riwayat-qc/pk-luar'))==(warehouse=='g2')


@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g1'),('operator','g2')])
async def test_document_guards_native_columns_parity_and_zero_mutation(pg,stok_lengkap,monkeypatch,role,warehouse):
    from app.penggilingan.gudang1.services import milling,drying
    from app.penggilingan.gudang2 import polishing
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as c:
        before=await _sidik(pg)
        for path in PATHS:
            native=await c.get(path,headers={'X-Pindah':'1'})
            shell=None
            async def forbidden(*args,**kwargs):pytest.fail('Document shell waited for heavy history reader')
            with monkeypatch.context() as m:
                m.setattr(milling,'riwayat_giling',forbidden)
                m.setattr(drying,'riwayat_pengeringan',forbidden)
                m.setattr(polishing,'riwayat_sosoh',forbidden)
                shell=await c.get(path,headers=HEADERS)
            if not allowed(role,warehouse,path):
                assert native.status_code==shell.status_code==403,path
                continue
            assert native.status_code==shell.status_code==200,(path,shell.text[-1000:])
            doc=BeautifulSoup(shell.text,'html.parser');root=doc.select_one('[data-riwayat-daftar-native]')
            assert root and root['data-url']==path
            assert 'Belum dibaca' in root.get_text() and not root.select('a[href],input,form')
            assert all(b.has_attr('disabled') for b in doc.select('[data-lk-cetak]'))
            expected=metadata(path)
            for label in expected['columns']:
                if label:assert label in root.get_text()
            native_doc=BeautifulSoup(native.text,'html.parser')
            assert not native_doc.select('[data-riwayat-daftar-native]')
            assert expected['header'] in native.text
            # X-Pindah wins even if foreground flags were inherited.
            repeated=await c.get(path,headers={**HEADERS,'X-Pindah':'1','X-Kerangka-Halaman':'1'})
            assert repeated.status_code==200
            assert not BeautifulSoup(repeated.text,'html.parser').select('[data-riwayat-daftar-native]')
            if path in PROCESS:
                cur=await c.get(path+'?sebelum=1',headers=HEADERS)
                assert BeautifulSoup(cur.text,'html.parser').select_one('[data-riwayat-daftar-native]')['data-url']==path+'?sebelum=1'
        assert await _sidik(pg)==before


@pytest.mark.parametrize('role,warehouse,path,qc',[
    ('admin',None,'/riwayat-giling','/riwayat-qc/gabah-basah'),
    ('operator','g1','/riwayat-giling','/riwayat-qc/pk-hasil-giling'),
    ('operator','g2','/riwayat-sosoh','/riwayat-qc/pk-luar'),
])
@pytest.mark.parametrize('width',[390,1280])
async def test_browser_delayed_native_get_error_retry_navigation(pg,stok_lengkap,monkeypatch,role,warehouse,path,qc,width):
    from app.web import riwayat_daftar_bertahap as family
    original=family.dokumen
    state=dict(target=None,gate=None,fail=False)
    async def controlled(request,akun):
        if request.headers.get('X-Pindah')=='1' and request.url.path==state['target']:
            if state['fail']:
                state['fail']=False
                raise HTTPException(503,'Synthetic owner read failure')
            if state['gate']:
                entered,release=state['gate'];state['gate']=None
                entered.set();await release.wait()
        return await original(request,akun)
    monkeypatch.setattr(family,'dokumen',controlled)
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as c:
        before=await _sidik(pg)
        native=BeautifulSoup((await c.get(path,headers={'X-Pindah':'1'})).text,'html.parser')
        expected=[' '.join(n.get_text(' ',strip=True).split()) for n in native.select('.rpd-stats>div')]
        async with peramban(c,width) as (page,transport):
            entered,release=asyncio.Event(),asyncio.Event()
            state.update(target=path,gate=(entered,release))
            try:
                await page.goto(BASE+path,wait_until='domcontentloaded')
                await asyncio.wait_for(entered.wait(),25)
                shell=page.locator('[data-riwayat-daftar-native]')
                await expect(shell).to_be_visible()
                await expect(shell.locator('[data-riwayat-native-status]')).to_contain_text('Memuat')
                if width==390:
                    fields=shell.locator('[data-riwayat-native-fields]')
                    await expect(fields).to_be_visible()
                    assert await fields.locator('dt').count()==len(metadata(path)['columns'])
                    assert set(await fields.locator('dd').all_text_contents())=={'Belum dibaca'}
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                await page.locator('[data-lk-buka=rpd-panduan]').focus()
                await page.locator('[data-lk-buka=rpd-panduan]').press('Enter')
                await expect(page.locator('#rpd-panduan')).to_be_visible()
                await page.locator('[data-rpd-guide-close]').click()
            finally:release.set()
            await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0,timeout=25000)
            actual=[' '.join(n.split()) for n in await page.locator('.rpd-stats>div').all_text_contents()]
            assert actual==expected
            out=Path(os.environ['DETAIL_OUT']);await page.screenshot(path=str(out/f'history-native-{role}-{warehouse}-{width}.png'),full_page=True)

            state.update(target=qc,fail=True)
            await page.goto(BASE+qc,wait_until='domcontentloaded')
            shell=page.locator('[data-riwayat-daftar-native]')
            await expect(shell.locator('[data-riwayat-native-status]')).to_contain_text('belum dapat dibaca')
            await expect(shell.locator('[data-riwayat-native-retry]')).to_be_visible()
            assert await shell.locator('.tabel-standar__kepala>span').count()==6
            await shell.locator('[data-riwayat-native-retry]').focus()
            await shell.locator('[data-riwayat-native-retry]').press('Enter')
            await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0,timeout=25000)
            assert await page.locator('.tabel-standar__kepala>span').count()==6
            assert await page.locator('[role=cell][aria-colspan="6"]').count()==1

            entered,release=asyncio.Event(),asyncio.Event()
            state.update(target=path,gate=(entered,release))
            try:
                await page.goto(BASE+path,wait_until='domcontentloaded')
                await asyncio.wait_for(entered.wait(),25)
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/barang-masuk"]').click()
            finally:release.set()
            await expect(page).to_have_url(re.compile('/barang-masuk$'),timeout=25000)
            await expect(page.locator('[data-riwayat-daftar-native]')).to_have_count(0)
            await expect(page.locator('[data-bm-page]')).to_be_visible(timeout=25000)
            assert transport['posts']==[]
            assert not transport['errors'],transport['errors']
        assert await _sidik(pg)==before
