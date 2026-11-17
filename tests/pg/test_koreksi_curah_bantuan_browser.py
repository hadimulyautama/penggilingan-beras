"""Actual read routes/session middleware on own PG, browser requests served by ASGI memory transport."""
from pathlib import Path
from urllib.parse import urlsplit
import os,json
import pytest
from sqlalchemy import select
from playwright.async_api import async_playwright,expect
from app.database import now_local
from app.models import User,PolishingProcess,PolishingOutputLog
from app.services import barang_keluar as bk
from app.penggilingan.inventory import finished_goods as fg
from tests.pg.test_barang_keluar import gudang,_klien,_pelanggan
from tests.pg.test_pengaturan_organisasi import fakta
from hmu_identitas import peran as P

@pytest.mark.asyncio
async def test_curah_help_existing_operator_admin_routes_read_only(pg,gudang):
    async with pg() as db:
        process=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses=='POL-BK-01'))
        db.add(PolishingOutputLog(polishing_process_id=process.id,jenis='broken',berat_kg=1000,waktu_update=now_local(),input_by=gudang['op']));await db.commit()
        await fg.catat_broken(db,user=await db.get(User,gudang['op']),kode_pol=process.kode_proses,berat_kg=1000)
    pid=await _pelanggan(pg,'Penerima Curah Bantuan Rekaan')
    async with pg() as db:
        order=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),baris=[bk.BarisPerintah(tipe='byproduct_curah',jenis='broken',berat_kg=450)],pelanggan_id=pid,metode='diantar',nama_ekspedisi='Angkutan Fixture')
        rid=order.rec.id;code=order.rec.kode
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=rid)
        await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rid)
    clients={P.OPERATOR:await _klien(pg,gudang['op'],'help-op',mode=P.OPERATOR),P.ADMIN:await _klien(pg,gudang['adm'],'help-adm',mode=P.ADMIN)}
    before=await fakta(pg)
    async with pg() as db:assert await fg.hitung_stok_byproduct_curah(db,'broken')==550
    engine=os.getenv('UJI_BROWSER','chromium');evidence=os.getenv('BUKTI_KOREKSI_CURAH');out=Path(evidence) if evidence else None
    if out:out.mkdir(parents=True,exist_ok=True)
    records=[]
    try:
      # Actual authenticated HTTP GET responses first; no operator corrective URL is attempted.
      for role,client in clients.items():
        page=await client.get(f'/barang-keluar/{rid}');assert page.status_code==200,page.text
        assert 'Hubungi <strong>Admin atau Super Admin</strong>' in page.text
      assert await fakta(pg)==before
      async with async_playwright() as pw:
        browser=await getattr(pw,engine).launch()
        try:
          for role,client in clients.items():
           for width in [390,1280]:
            ctx=await browser.new_context(viewport={'width':width,'height':920},service_workers='block',color_scheme='light',reduced_motion='reduce')
            requests=[];blocked=[];errors=[]
            await ctx.add_cookies([{'name':c.name,'value':c.value,'url':'http://uji'} for c in client.cookies.jar])
            await ctx.add_init_script('window.EventSource=undefined;window.print=()=>{throw Error("No physical printing")};')
            async def route(r):
                u=urlsplit(r.request.url);requests.append({'method':r.request.method,'path':u.path})
                if u.netloc=='fonts.googleapis.com' and r.request.resource_type=='stylesheet':
                    return await r.fulfill(status=200,content_type='text/css',body='/* offline fixture uses system font */')
                if u.netloc!='uji' or r.request.method!='GET':blocked.append(r.request.url);return await r.abort()
                if u.path.endswith(('.pdf','.csv')) or '/timbang' in u.path:blocked.append(r.request.url);return await r.abort()
                request_headers={k:v for k,v in r.request.headers.items() if k.lower() not in {'cookie','host','content-length','connection'}}
                resp=await client.get(u.path+('?' +u.query if u.query else ''),headers=request_headers)
                headers={k:v for k,v in resp.headers.items() if k.lower() not in {'content-length','content-encoding','transfer-encoding','connection'}}
                return await r.fulfill(status=resp.status_code,headers=headers,body=resp.content)
            await ctx.route('**/*',route);page=await ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            try:
              await page.goto(f'http://uji/barang-keluar/{rid}');await page.wait_for_load_state('networkidle')
              await expect(page.locator('#sesi-berubah')).to_have_count(0)
              help=page.locator('[data-bantuan-koreksi-curah]');await expect(help).to_be_visible();await expect(help).to_contain_text('Admin atau Super Admin');await expect(help).to_contain_text(code)
              summary=help.locator('[data-curah-langkah] summary');await summary.focus();await page.keyboard.press('Enter')
              await expect(help.locator('[data-curah-langkah]')).to_have_attribute('open','')
              if out:await page.screenshot(path=str(out/f'{engine}-{role}-curah-expanded-{width}.png'),full_page=True)
              await expect(help).to_contain_text('450 kg');await expect(help).to_contain_text('jumlah yang benar dalam kg')
              assert await help.locator('form,button').count()==0
              if role==P.OPERATOR:
                assert await help.locator('a').count()==0
                await expect(help).to_contain_text('Petunjuk ini tidak mengirim pengajuan')
              else:
                link=help.locator('[data-curah-perbaikan]');await link.focus();await page.keyboard.press('Enter')
                await expect(page.get_by_role('heading',name='Perbaiki pengiriman',exact=True)).to_be_visible()
                link=page.get_by_role('link',name='Koreksi pengiriman terverifikasi '+code,exact=True);await link.focus();await page.keyboard.press('Enter')
                await expect(page.get_by_role('heading',name='Koreksi pengiriman terverifikasi',exact=True)).to_be_visible()
                await expect(page.locator('[data-items] [name=jumlah]')).to_have_value('450.00')
                await expect(page.locator('#sesi-berubah')).to_have_count(0)
                await page.goto(f'http://uji/barang-keluar/{rid}');await page.wait_for_load_state('networkidle')
              assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
              fold=page.locator('[data-curah-langkah]')
              if await fold.get_attribute('open') is not None:
                await fold.locator('summary').focus();await page.keyboard.press('Enter')
              if out:await page.screenshot(path=str(out/f'{engine}-{role}-curah-{width}.png'),full_page=True)
              assert not blocked and not errors,(blocked,errors)
              assert await fakta(pg)==before
              records.append({'role':role,'width':width,'actual_curah_route':True,'existing_signed_fixture_session':True,'Admin_native_correction_reached':role==P.ADMIN,'operator_instruction_to_Admin':True,'no_request_workflow_claimed':True,'no_POST':all(r['method']=='GET' for r in requests),'all_table_fingerprints_unchanged':len(before),'overflow':False})
            finally:await ctx.close()
        finally:await browser.close()
      assert len(records)==4
      if out:(out/'result.json').write_text(json.dumps({'status':'PASS_READ_ONLY_UI','engine':engine,'records':records,'source':'Official gudang fixture+catat_broken1000 and normal PadiFlow450kg final setup; no corrective save/retest','stock_curah_before_after':550,'recorded_outgoing_before_after':450,'table_count':len(before),'native_login_form_tested':False,'middleware_checked':True,'server_listener':False,'limits':['Signed sessions belong only to new synthetic users; no real accounts','No450→400save; independent QA result not repeated','No NET prototype or held feature is part of this test']},indent=2))
    finally:
      for client in clients.values():await client.aclose()
