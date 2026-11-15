"""Pratinjau kandidat dari template aplikasi dan fixture sintetis, tanpa data live."""
import os
import uuid
from pathlib import Path
import pytest
from playwright.async_api import expect
from sqlalchemy import select
from app.models import User,FinishedGoodsStock,ByproductStock,TransferBarang
from app.services import transfer_barang as requests,perintah_transfer
from tests.pg.test_transfer_barang import lokasi
from tests.pg.test_kepemilikan_koreksi import world
from tests.pg.test_transfer_pk_halaman import browser_app,BASE
pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('peran,gudang,label',[('admin',None,'admin'),('operator','Gudang 2','operator-asal')])
async def test_preview_daftar_dengan_permintaan_dan_perintah_sintetis(pg,lokasi,width,peran,gudang,label):
    out=os.environ.get('UJI_TRANSFER_PREVIEW')
    if not out:pytest.skip('UJI_TRANSFER_PREVIEW belum dipilih')
    w=lokasi
    async with pg() as db:
        stock=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.jasa_id.is_(None),FinishedGoodsStock.warehouse_id==w['wh']))
        (await db.get(ByproductStock,w['broken'])).jasa_id=None
        await db.commit();sid=stock.id
        await perintah_transfer.buat(db,user=await db.get(User,w['user']),jenis='barang',sumber_id=str(sid),asal_id=w['wh'],tujuan_id=w['target'],jumlah='5',kunci=uuid.uuid4().hex)
        for kind,ident,n in [('curah',w['broken'],'200.5'),('karung',w['pack'],'100')]:
            await requests.minta(db,user=await db.get(User,w['penerima']),jenis=kind,id=str(ident),tujuan_id=w['target'],jumlah=n,kunci_kiriman=uuid.uuid4().hex)
        assert await db.scalar(select(TransferBarang.id).limit(1)) is None
    async with browser_app(pg,peran=peran,gudang=gudang,width=width) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await expect(page.locator('#tp-segar')).to_have_attribute('data-status','segar')
        await expect(page.locator('#pk-request-stats')).to_contain_text('Menunggu Admin2')
        await expect(page.locator('#pk-daftar .riwayat-list article')).to_have_count(3)
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        if width>=900:
            assert await page.locator('#pk-daftar .tp-request-grid>span').evaluate_all('cells=>cells.every(c=>c.scrollWidth<=c.clientWidth+2)')
            if peran=='admin':assert await page.locator('#tb-buka').evaluate('e=>e.getBoundingClientRect().width')<250
        output=Path(out);output.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(output/f'transfer-kandidat-{label}-{width}.png'),full_page=True)
