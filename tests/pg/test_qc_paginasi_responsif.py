"""Label navigasi QC tetap utuh; perpindahan putaran hanya mengubah tampilan."""
import os
import pytest
from sqlalchemy import select,func
from app.models import ActivityLog
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_QC_PAGINASI')!='1',reason='Browser lokal opsional')]

@pytest.mark.parametrize('width',[320,390,768,1440])
async def test_paginasi_utuh_dan_pilihan_putaran_tetap(pg,qc,width):
 from playwright.async_api import expect
 async with await _klien(pg,peran='superadmin') as c:
  async with browser(c,width) as page:
   async with pg() as db:before=await db.scalar(select(func.count()).select_from(ActivityLog))
   for jenis,ref,n in [('gabah-basah','GB-QC-BASAH',5),('gabah-kering','GB-QC-KERING',5),('pk-hasil-giling','LOT-QC-DETAIL',3),('pk-luar','PKB-QC-DETAIL',1)]:
    path=f'/riwayat-qc/{jenis}/{ref}?tab_qc=putaran'
    r=await page.goto(path);assert r.status==200
    await page.locator('[data-rqd-ready]').wait_for()
    for javascript in [False,True]:
     if javascript:
      await page.select_option('#qc-putaran','1');await page.locator('.qc-picker button').click()
      await expect(page.locator('.qc-history-round:visible')).to_have_attribute('data-posisi','1')
     parts=await page.locator('.kontrol-paginasi__tombol').evaluate_all('es=>es.map(e=>{const q=document.createRange();q.selectNodeContents(e);const r=e.getBoundingClientRect();return {lines:q.getClientRects().length,x:r.x,y:r.y,w:r.width,h:r.height,client:e.clientWidth,scroll:e.scrollWidth}})')
     assert len(parts)==2 and all(x['lines']==1 and x['h']>=44 and x['scroll']<=x['client'] for x in parts),parts
     assert parts[0]['y']==parts[1]['y'] and parts[0]['x']+parts[0]['w']<=parts[1]['x']
     count=await page.locator('.kontrol-paginasi__posisi').bounding_box()
     if width<=650:assert count['y']>=parts[0]['y']+parts[0]['h']
     assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
    await expect(page.locator('.kontrol-paginasi__tombol').first).to_have_attribute('aria-disabled','true')
    if n>1:
     await page.locator('.kontrol-paginasi__tombol').last.click()
     await expect(page.locator('.qc-history-round:visible')).to_have_attribute('data-posisi','2')
     await page.reload();await page.locator('[data-rqd-ready]').wait_for()
     await expect(page.locator('#qc-putaran')).to_have_value('2')
    else:await expect(page.locator('.kontrol-paginasi__tombol').last).to_have_attribute('aria-disabled','true')
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==before
