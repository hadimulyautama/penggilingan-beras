"""Satu keputusan di detail asli, memakai sesi peran dan PostgreSQL sungguhan."""
import asyncio,os,socket
from pathlib import Path
from contextlib import asynccontextmanager
import pytest,uvicorn
from playwright.async_api import async_playwright,expect
from sqlalchemy import select,func,text
from app.models import OutgoingRecord,ActivityLog
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_verifikasi_pengiriman import _setup,_items
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_VERIFIKASI_BROWSER')!='1',reason='Audit browser lokal opt-in')]

@asynccontextmanager
async def server():
 from app.main import app
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 srv=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,lifespan='off',access_log=False,log_level='error'));task=asyncio.create_task(srv.serve())
 try:
  for _ in range(150):
   if srv.started:break
   await asyncio.sleep(.02)
  assert srv.started
  yield f'http://127.0.0.1:{port}'
 finally:srv.should_exit=True;await task

@pytest.mark.parametrize('engine,width',[('chromium',1440),('chromium',390),('webkit',1440),('webkit',390)])
async def test_detail_satu_klik_alasan_basi_dan_akses(pg,gudang,engine,width):
 rs,tid=await _setup(pg,gudang,5);rid=rs[0].rec.id
 awal=await _items(pg);stok=await _stok(pg,gudang)
 async with await _klien(pg,gudang['adm'],'audit-admin') as ca,await _klien(pg,gudang['op'],'audit-op',mode='operator') as co,server() as host,async_playwright() as pw:
  browser=await getattr(pw,engine).launch()
  options=dict(pw.devices['iPhone 13']) if width==390 and engine=='webkit' else {}
  options.pop('default_browser_type',None);options.update(viewport={'width':width,'height':1000},has_touch=width==390,is_mobile=width==390,service_workers='block',timezone_id='Asia/Jakarta')
  ctx=await browser.new_context(**options);await ctx.add_cookies([dict(name=c.name,value=c.value,url=host) for c in ca.cookies.jar])
  page=await ctx.new_page();errors=[];posts=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('request',lambda r:posts.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/api/actions/verifikasi-keluar') else None)
  await page.route('https://**/*',lambda r:r.abort())
  root=page.locator('[data-verifikasi-pengiriman][data-inline]');url=host+f'/barang-keluar/{rid}'
  async def press(loc):
   if width==390:await loc.tap()
   else:await loc.click()
  try:
   await page.goto(url);await expect(root.get_by_role('button',name='Verifikasi pengiriman',exact=True)).to_be_enabled()
   assert await page.locator('a[href*="/verifikasi-pengiriman"]').count()==0
   out=Path(os.environ.get('UJI_AUDIT_OUT','/tmp'));out.mkdir(exist_ok=True,parents=True)
   await root.screenshot(path=str(out/f'{engine}-{width}-siap.png'))
   # Data berubah di belakang layar: konteks tetap, belum ada penulisan.
   async with pg() as db:await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=826 WHERE id=:id'),{'id':tid});await db.commit()
   await press(root.get_by_role('button',name='Verifikasi pengiriman',exact=True))
   await expect(root.locator('[data-galat]')).to_contain_text('Data pemeriksaan berubah')
   assert not posts
   await press(root.get_by_role('button',name='Periksa data terbaru'))
   reason=root.locator('#vv-sebab');await expect(reason).to_be_visible();assert await reason.get_attribute('aria-required')=='true'
   await press(root.get_by_role('button',name='Verifikasi pengiriman',exact=True));await expect(root.locator('[data-galat]')).to_contain_text('Tuliskan sebab')
   assert not posts
   await reason.fill('Selisih diperiksa Admin di armada')
   await root.screenshot(path=str(out/f'{engine}-{width}-alasan.png'))
   # Satu tap setelah mengetik; tidak ada layar/dialog review kedua.
   await press(root.get_by_role('button',name='Verifikasi pengiriman',exact=True))
   await expect(root.get_by_role('heading',name='Pengiriman terverifikasi',exact=True)).to_be_visible(timeout=15000)
   assert len(posts)==1 and posts[0]['sebab_selisih']=='Selisih diperiksa Admin di armada'
   assert page.url.startswith(url) and len(ctx.pages)==1
   assert await root.get_by_role('button',name='Verifikasi pengiriman',exact=True).count()==0
   await press(root.get_by_text('Rincian pemeriksaan pengiriman',exact=True));await expect(root).to_contain_text('Tara lain');await expect(root).to_contain_text('Muatan menurut catatan PadiFlow')
   assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   out=Path(os.environ.get('UJI_AUDIT_OUT','/tmp'));out.mkdir(exist_ok=True,parents=True)
   await page.screenshot(path=str(out/f'{engine}-{width}-hasil.png'),full_page=True)
   async with pg() as db:
    records=list((await db.scalars(select(OutgoingRecord))).all());assert all(r.status=='selesai' and r.sebab_selisih==posts[0]['sebab_selisih'] for r in records)
    assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))==2
   assert await _items(pg)==awal and await _stok(pg,gudang)==stok
   # Kasus normal: tanpa membuka catatan opsional, satu klik sukses.
   async with pg() as db:
    await db.execute(text("UPDATE timbangan_transaksi SET kode='KLR-AUDIT-AWAL' WHERE id=:id"),{'id':tid});await db.commit()
   rs2,_=await _setup(pg,gudang,5);rid2=rs2[0].rec.id
   await page.goto(host+f'/barang-keluar/{rid2}');await expect(root.get_by_role('button',name='Verifikasi pengiriman',exact=True)).to_be_enabled()
   assert not await root.locator('#vv-sebab').is_visible()
   await press(root.get_by_role('button',name='Verifikasi pengiriman',exact=True));await expect(root.get_by_role('heading',name='Pengiriman terverifikasi',exact=True)).to_be_visible(timeout=15000)
   assert len(posts)==2 and posts[1]['sebab_selisih']==''
   # Operator boleh melihat detail tetapi tidak mendapat kontrol Admin.
   opctx=await browser.new_context(**options);await opctx.add_cookies([dict(name=c.name,value=c.value,url=host) for c in co.cookies.jar]);op=await opctx.new_page()
   await op.goto(host+f'/barang-keluar/{rid2}?rincian_perintah=1');assert await op.locator('[data-verifikasi-pengiriman]').count()==0
   await opctx.close();assert not errors,errors
  finally:await ctx.close();await browser.close()

async def test_halaman_pemeriksaan_lama_tetap_berfungsi(pg,gudang):
 rs,_=await _setup(pg,gudang,5)
 async with await _klien(pg,gudang['adm'],'audit-lama') as ca,server() as host,async_playwright() as pw:
  browser=await pw.chromium.launch();ctx=await browser.new_context(service_workers='block');await ctx.add_cookies([dict(name=c.name,value=c.value,url=host) for c in ca.cookies.jar]);page=await ctx.new_page()
  try:
   await page.goto(host+'/verifikasi-pengiriman?perintah='+str(rs[0].rec.id))
   await page.get_by_role('button',name='Periksa verifikasi manual',exact=True).click()
   await page.get_by_role('button',name='Verifikasi seluruh kiriman',exact=True).click()
   await expect(page.get_by_role('heading',name='Hasil verifikasi pengiriman',exact=True)).to_be_visible()
  finally:await ctx.close();await browser.close()
