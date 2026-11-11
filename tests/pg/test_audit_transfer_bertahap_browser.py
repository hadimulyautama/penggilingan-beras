"""Audit peran pada UI asli dua aplikasi dan PostgreSQL lokal, tanpa mock API."""
import asyncio,os,socket,subprocess,json
from pathlib import Path
from decimal import Decimal
from contextlib import asynccontextmanager
import pytest,httpx,uvicorn
from sqlalchemy import select,func,text
from playwright.async_api import async_playwright,expect
from app.models import User,Warehouse,Silo,PermintaanPk,PengirimanPk,InternalTransfer
from hmu_identitas.model import Akun
from app.config import settings
from app.services import transfer
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_riwayat_giling import _klien
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_AUDIT_TRANSFER')!='1',reason='Audit dua aplikasi lokal memerlukan profil uji khusus.')]
OUT=Path(os.environ.get('UJI_AUDIT_OUT','../audit-transfer'))

def port_bebas():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

@asynccontextmanager
async def aplikasi(pg,monkeypatch):
 from app.main import app
 pp,tp=port_bebas(),port_bebas();pf=f'http://127.0.0.1:{pp}';tf=f'http://127.0.0.1:{tp}'
 monkeypatch.setattr(settings,'teraflow_web_url',tf);monkeypatch.setattr(settings,'internal_api_token','uji-audit-transfer-lokal')
 config=uvicorn.Config(app,host='127.0.0.1',port=pp,lifespan='off',access_log=False,log_level='error');server=uvicorn.Server(config);task=asyncio.create_task(server.serve())
 while not server.started:
  if task.done():await task
  await asyncio.sleep(.02)
 env={**os.environ,'DATABASE_URL':os.environ['UJI_PG_URL'],'PRODUKSI_API_URL':pf,'PRODUKSI_WEB_URL':pf,'PRODUKSI_API_TOKEN':'uji-audit-transfer-lokal','TIMBANGAN_SECRET_KEY':'uji-kunci-tera-lokal-untuk-audit-bukan-produksi','PYTHONPATH':os.environ['UJI_TERAFLOW_ROOT']}
 OUT.mkdir(parents=True,exist_ok=True);log=(OUT/'tera-server.log').open('a')
 tera=subprocess.Popen([os.environ['UJI_TERAFLOW_PYTHON'],'-m','uvicorn','app.timbangan.main:app','--host','127.0.0.1','--port',str(tp),'--lifespan','off','--log-level','error'],cwd=os.environ['UJI_TERAFLOW_ROOT'],env=env,stdout=log,stderr=subprocess.STDOUT)
 try:
  # Semai aturan melalui interpreter aplikasi yang memilikinya.
  seed='import asyncio\nfrom app.database import SessionLocal\nfrom app.timbangan import service\nasync def run():\n async with SessionLocal() as db:await service.pastikan_jenis(db)\nasyncio.run(run())'
  r=await asyncio.to_thread(subprocess.run,[os.environ['UJI_TERAFLOW_PYTHON'],'-c',seed],cwd=os.environ['UJI_TERAFLOW_ROOT'],env=env,capture_output=True,text=True);assert r.returncode==0,r.stderr
  async with httpx.AsyncClient() as c:
   for _ in range(100):
    try:
     r=await c.get(tf+'/health')
     if r.status_code==200:break
    except httpx.HTTPError:pass
    await asyncio.sleep(.05)
   else:raise AssertionError('Server TeraFlow uji belum siap')
  yield pf,tf
 finally:
  tera.terminate();await asyncio.to_thread(tera.wait,timeout=10);log.close();server.should_exit=True;await task

async def tekan(locator):
 if locator.page.viewport_size['width']<=430:
  await locator.tap();locator.page._audit_taps=getattr(locator.page,'_audit_taps',0)+1
 else:await locator.click()

async def buka(page,url):
 r=await page.goto(url);assert r and r.status<400,(url,r.status if r else None)
 await expect(page.locator('#pk-pesan')).to_have_text('Status diperbarui.')
 assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')

async def angka(page,name,value):
 field=page.locator(f'form.fw-form [name="{name}"]')
 if await field.count():
  if not await field.is_visible():await field.evaluate('e=>{let p=e.closest("details");if(p)p.open=true}')
  await field.fill(str(value))

@pytest.mark.parametrize('width',[int(v) for v in os.getenv('UJI_LAYAR','320,390,768,1440').split(',')])
@pytest.mark.parametrize('tujuan',['ditumpuk','Silo A'])
async def test_operator_admin_sebagian_silo_dan_selisih_asli(pg,pabrik,monkeypatch,width,tujuan):
 OUT.mkdir(parents=True,exist_ok=True)
 async with pg() as db:
  silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'));silo.kapasitas_ton=10;await db.commit()
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c2,await _klien(pg,peran='operator',gudang='Gudang 1') as c1,await _klien(pg,peran='admin') as ca:
  async with pg() as db:akun=await db.scalar(select(Akun).order_by(Akun.id.desc()).offset(1).limit(1));username=akun.username
  async with aplikasi(pg,monkeypatch) as (pf,tf),async_playwright() as pw:
   engine=os.getenv('UJI_BROWSER','chromium');assert engine in ('webkit','chromium')
   b=await getattr(pw,engine).launch();contexts=[];pages=[];errors=[];network=[]
   try:
    for client in (c2,c1,ca):
     options=dict(pw.devices['iPhone 13']) if width<=430 and engine=='webkit' else {}
     options.update(timezone_id='Asia/Jakarta',viewport=dict(width=width,height=1000),is_mobile=width<=430,has_touch=width<=430,service_workers='block',reduced_motion='reduce');options.pop('default_browser_type',None)
     ctx=await b.new_context(**options);contexts.append(ctx)
     await ctx.add_cookies([dict(name=c.name,value=c.value,url=pf) for c in client.cookies.jar])
     await ctx.add_init_script("window.__auditTouchCount=0;window.addEventListener('touchstart',()=>window.__auditTouchCount++,{passive:true});")
     page=await ctx.new_page();page.on('pageerror',lambda e,p=page:errors.append(dict(message=str(e),stack=e.stack,url=p.url)))
     page.on('requestfailed',lambda r:network.append(dict(url=r.url,failure=r.failure)))
     page.on('response',lambda r:network.append(dict(url=r.url,status=r.status)) if '/kiriman/sesi' in r.url else None)
     await page.route('https://**/*',lambda r:r.abort());pages.append(page)
    dest,source,admin=pages
    # Permintaan dibuat lewat dialog detail lot, bukan daftar lot yang ditebak.
    await dest.goto(pf+'/stok/pk/detail?gudang=g1&kode='+pabrik['lot']+'&pemilik_id=pabrik')
    await tekan(dest.get_by_role('link',name='Minta lot ini',exact=True));dialog=dest.locator('#lembar[open]');await expect(dialog).to_be_visible()
    await dialog.locator('[data-name=cara]').select_option('kg');await dialog.locator('[data-name=berat]').fill('6000')
    await tekan(dialog.get_by_role('button',name='Minta PK',exact=True));await expect(dialog).not_to_be_visible()
    async with pg() as db:r=await db.scalar(select(PermintaanPk));rid=r.id;assert r.bertahap and r.status=='diminta'
    await buka(dest,pf+'/transfer-bertahap');await expect(dest.locator(f'#pk-daftar [data-id="{rid}"]')).to_contain_text('Menunggu persetujuan Admin');assert await dest.locator('[name=pilih]').count()==0
    # Admin memeriksa jumlah & tujuan inline, lalu langsung menyetujui.
    await buka(admin,pf+'/transfer-bertahap');row=admin.locator(f'#pk-daftar [data-id="{rid}"]');await row.locator('[name=pilih]').check();await row.locator('[name=berat]').fill('6000');await row.locator('[name=tujuan]').select_option(tujuan)
    await tekan(admin.get_by_role('button',name='Setujui 1 permintaan dipilih',exact=True));await expect(admin.locator('#pk-pesan')).to_have_text('Permintaan dipilih telah disetujui.')
    scenario=[]
    for index,(amount,actual) in enumerate([(2000,1995),(4000,3980 if width in (430,768,1440) else 3960)]):
     await buka(source,pf+'/transfer-bertahap');row=source.locator(f'#pk-daftar [data-id="{rid}"]');await row.locator('[name=pilih]').check();await row.locator('[name=berat]').fill(str(amount));await source.locator('[name=nomor_polisi]').fill('K 9773 J');await source.locator('[name=nama_sopir]').fill('Kasidi')
     await tekan(source.get_by_role('button',name='Buat 1 perjalanan · 1 lot',exact=True));await expect(source.locator('#pk-pesan')).to_contain_text('tersimpan. Buka timbang perjalanan')
     async with pg() as db:j=await db.scalar(select(PengirimanPk).order_by(PengirimanPk.id.desc()));jid=j.id;assert await transfer.saldo_pk(db,pabrik['proses_id'])==(6000 if index==0 else 4000)
     response=await source.request.get(pf+'/api/transfer-bertahap');data=await response.json();assert data['permintaan'][0]['sisa']==('4000' if index==0 else '0')
     # Operator tujuan melihat perjalanan, tanpa langkah konfirmasi penerimaan.
     await buka(dest,pf+'/transfer-bertahap');assert await dest.locator('[name=pilih],[data-action]').count()==0;await expect(dest.locator(f'#perjalanan-{jid}')).to_contain_text('Menunggu timbang')
     href=await source.locator(f'#perjalanan-{jid} a').get_attribute('href');assert 'pengiriman_pk_id='+str(jid) in href
     await source.goto(href)
     if '/masuk' in source.url:
      await source.locator('[name=username]').fill(username);await source.locator('[name=sandi]').fill('rahasia123');await tekan(source.get_by_role('button',name='Masuk',exact=True));await source.wait_for_url(lambda u:'/masuk' not in u,timeout=15000)
     await expect(source.locator('[name=pengiriman_pk_id]')).to_have_value(str(jid));await expect(source.locator('[name=nomor_polisi]')).to_have_value('K 9773 J')
     await angka(source,'berat_kg',8500);await angka(source,'jumlah_karung',amount//50);await angka(source,'tara_per_karung_kg',0)
     await tekan(source.get_by_role('button',name='Simpan timbang pertama',exact=True));await tekan(source.get_by_role('link',name='Lanjutkan timbang kedua',exact=True));await expect(source.get_by_role('heading',name='Timbang kedua',exact=True)).to_be_visible()
     await expect(source.get_by_role('heading',name=f'Perjalanan PK #{jid}',exact=True)).to_be_visible()
     await angka(source,'berat_kg',8500-actual);await angka(source,'tara_per_karung_kg',0)
     await tekan(source.get_by_role('button',name='Selesaikan penimbangan',exact=True));await expect(source.get_by_role('heading',name='Detail riwayat timbang',exact=True)).to_be_visible()
     async with pg() as db:
      j=await db.get(PengirimanPk,jid);assert j.bobot_timbang_kg==actual,(j.bobot_timbang_kg,actual)
      assert j.status==('selesai' if index==0 else 'menunggu_admin')
      if index==1:assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==2000
     assert await source.evaluate('document.documentElement.scrollWidth<=innerWidth')
     await source.screenshot(path=str(OUT/f'tera-{width}-{tujuan.replace(" ","-")}-{index}.png'),full_page=True)
     if index==1:
      await buka(admin,pf+'/transfer-bertahap');card=admin.locator(f'#perjalanan-{jid}');await expect(card).to_contain_text('Selisih · perlu Admin');assert await dest.locator('[data-action=terima-selisih]').count()==0
      await tekan(card.get_by_role('button',name='Periksa & terima selisih',exact=True));await admin.locator('#pk-alasan [name=alasan]').fill('Muatan asal dan hasil timbang sudah diperiksa; selisih diterima.')
      await tekan(admin.get_by_role('button',name='Simpan keputusan',exact=True));await expect(admin.locator('#pk-pesan')).to_have_text('Keputusan tersimpan.')
      # Jalankan tugas sinkronisasi yang sama dengan pekerja latar sebenarnya.
      # HTTP internal dan database tetap nyata; tidak ada callback tiruan.
      code='import asyncio\nimport app.timbangan.main\nfrom app.timbangan.transfer_pk import sinkron_tertunda\nfrom app.database import dapatkan_engine\nasync def run():\n await sinkron_tertunda()\n await dapatkan_engine().dispose()\nasyncio.run(run())'
      env={**os.environ,'DATABASE_URL':os.environ['UJI_PG_URL'],'PRODUKSI_API_URL':pf,'PRODUKSI_API_TOKEN':'uji-audit-transfer-lokal','PYTHONPATH':os.environ['UJI_TERAFLOW_ROOT']}
      result=await asyncio.to_thread(subprocess.run,[os.environ['UJI_TERAFLOW_PYTHON'],'-c',code],cwd=os.environ['UJI_TERAFLOW_ROOT'],env=env,capture_output=True,text=True,timeout=30);assert result.returncode==0,result.stderr
      await source.reload();await expect(source.get_by_text('Transfer selesai · stok telah tercatat',exact=True)).to_be_visible()

     scenario.append(dict(perjalanan=jid,muatan=amount,timbang=actual,penyelesaian='otomatis' if index==0 else 'Admin'))
    await buka(dest,pf+'/transfer-bertahap');await expect(dest.locator(f'#pk-daftar [data-id="{rid}"]')).to_contain_text('Selesai');assert await dest.locator('[data-action]').count()==0
    async with pg() as db:
     r=await db.get(PermintaanPk,rid);assert r.status=='selesai' and r.berat_final_kg==6000 and r.berat_setuju_kg==6000
     assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==6000
     assert await transfer.saldo_pk(db,pabrik['proses_id'])==0
     if tujuan=='Silo A':
      from app.penggilingan.gudang2.service import hitung_stok_silo
      silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'));assert await hitung_stok_silo(db,silo.id)==6000
     else:
      from app.penggilingan.gudang2.service import hitung_stok_tumpukan
      assert await hitung_stok_tumpukan(db)==6000
    await admin.screenshot(path=str(OUT/f'admin-{width}-{tujuan.replace(" ","-")}.png'),full_page=True)
    assert not errors,errors
    if width<=430:
     assert all(getattr(p,'_audit_taps',0)>0 for p in pages)
     assert await admin.evaluate('window.__auditTouchCount')>=2
    (OUT/f'hasil-{width}-{tujuan.replace(" ","-")}.json').write_text(json.dumps(dict(width=width,tujuan=tujuan,engine=engine,browser_version=b.version,user_agent=await source.evaluate('navigator.userAgent'),touch=await source.evaluate('navigator.maxTouchPoints'),touch_context=width<=430,tap_actions={role:getattr(p,'_audit_taps',0) for role,p in zip(('tujuan','asal','admin'),pages)},operator_tujuan_tanpa_konfirmasi=True,perjalanan=scenario,stok_akhir=6000,sinkron_keputusan_admin=True),indent=2))
   except BaseException:
    diagnostic={}
    for role,page in zip(('tujuan','asal','admin'),pages):
     try:
      await page.screenshot(path=str(OUT/f'gagal-{role}-{width}.png'),full_page=True)
      diagnostic[role]=await page.evaluate("""() => ({url:location.href,forms:[...document.forms].map(f=>({id:f.id,invalid:[...f.elements].filter(e=>e.willValidate&&!e.validity.valid).map(e=>({name:e.name,value:e.value,message:e.validationMessage,html:e.outerHTML}))})),pesan:document.querySelector('#pk-pesan')?.textContent})""")
     except Exception as e:diagnostic[role]=str(e)
    diagnostic['js_errors']=errors;diagnostic['network']=network
    (OUT/'diagnostik-gagal.json').write_text(json.dumps(diagnostic,indent=2))
    raise
   finally:await b.close()
