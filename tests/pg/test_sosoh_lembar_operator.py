"""Dua tampilan, satu sumber dan layanan asli, data PostgreSQL terpisah."""
from pathlib import Path
import pytest
from sqlalchemy import select, func
from app.models import PolishingOutputLog, ActivityLog
from tests.pg.test_koreksi_bahan_berjalan import running, dunia
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_muat_sekali_browser import BASE
from tests.pg.formulir import cap_formulir

from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import asyncio

@asynccontextmanager
async def browser_client(client,width,fault=None):
 from playwright.async_api import async_playwright
 async with async_playwright() as pw:
  browser=await pw.chromium.launch()
  ctx=await browser.new_context(viewport={'width':width,'height':1000},service_workers='block')
  await ctx.add_cookies([{'name':k.name,'value':k.value,'url':BASE} for k in client.cookies.jar])
  writes=[];pending=set();closing=False
  async def route(r):
   task=asyncio.current_task();pending.add(task)
   try:
    req=r.request;target=urlsplit(req.url)
    if closing or not req.url.startswith(BASE+'/'):await r.abort();return
    if target.path=='/api/aliran':await r.fulfill(status=204,body='');return
    if req.method!='GET':writes.append(target.path)
    response=await client.request(req.method,target.path+('?' + target.query if target.query else ''),content=req.post_data_buffer,headers={k:v for k,v in req.headers.items() if k.lower() in ('content-type','x-csrf-token','x-pindah','accept')})
    if fault and fault(target.path,req.method):await r.abort();return
    await r.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding')})
   finally:pending.discard(task)
  await ctx.route('**/*',route)
  page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  try:yield page,writes,errors
  finally:
   closing=True
   # Finish in-flight ASGI reads before closing browser / resetting test schema.
   if pending:await asyncio.gather(*list(pending),return_exceptions=True)
   await ctx.close();await browser.close()

pytestmark = pytest.mark.asyncio
OUT = Path('output/sosoh-lembar-operator-20261108')

@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('role,view,operator',[
 ('admin',None,False),('superadmin',None,False),('operator',None,True),
 ('superadmin','operator:g2',True),('superadmin','admin',False)])
async def test_tampilan_peran_efektif_dan_draf(pg,running,width,role,view,operator):
 from playwright.async_api import expect
 uid,kode,mid,intake=running
 async with await _klien(pg,peran=role,gudang='Gudang 2') as c:
  if view:c.cookies.set('produksi_lihat',view)
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode)
   root=page.locator('[data-sosoh-ringkas]')
   await expect(root).to_have_attribute('data-layout','operator' if operator else 'admin')
   await expect(root.locator('[data-kb-entry]').first).to_be_attached()
   if operator:
    await expect(root.locator('.sr-worksheet')).to_have_count(0) # root itself carries class
    assert 'sr-worksheet' in await root.get_attribute('class')
    assert await root.locator('[data-sr-tab]').count()==0
    await expect(root.locator('[data-kb-output="medium"] input')).to_be_visible()
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('Susut/selisih sementara: 300 kg')
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('12%')
    await expect(root.locator('[data-kb-output="medium"] .sr-work-percent')).to_contain_text('80%')
    assert await root.get_by_role('tab').count()==0
    field=root.locator('[data-kb-output="medium"] input');await field.fill('2100')
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('belum disimpan')
    await expect(root.locator('[data-kb-output="medium"] .sr-work-percent')).to_contain_text('84%')
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('8%')
    await root.locator('[data-sr-fold="qcTerbuka"]>summary').click()
    await expect(root.locator('.sr-work-result-balance')).to_be_visible()
    assert await field.input_value()=='2100'
    await field.fill('2000')
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('Neraca hasil tercatat')
   else:
    assert await root.locator('[data-sr-tab]').count()==5
    await expect(root.locator('.sr-design-mass')).to_contain_text('12% dari bahan')
    assert await root.locator('.sr-design-overview').count()==1
    await expect(root.get_by_role('button',name='Catat hasil',exact=True)).to_be_visible()
    await root.get_by_role('button',name='Catat hasil',exact=True).click()
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('Susut/selisih sementara: 300 kg')
    field=root.locator('[data-kb-output="medium"] input');await field.fill('2100')
    await expect(root.locator('[data-kb-output="medium"] .sr-work-percent')).to_contain_text('84%')
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('pratinjau: 200 kg')
    await field.fill('2000')
    await expect(root.locator('.sr-work-result-balance')).to_contain_text('Neraca hasil tercatat')
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   OUT.mkdir(parents=True,exist_ok=True)
   await page.get_by_role('heading',name='Catat hasil & neraca' if operator else 'Catat hasil penyosohan',exact=True).scroll_into_view_if_needed()
   if role=='operator' and view is None:
    await root.locator('#hasil').screenshot(path=str(OUT/f'hasil-neraca-{width}.png'))
   await page.screenshot(path=str(OUT/f'{role}-{view or "asli"}-{width}.png'),full_page=True)
   assert not errors,errors
   # Preview is read only; there must be no operational save request.
   assert all(path.endswith('/neraca/pratinjau') for path in writes),writes
 async with pg() as db:
  assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2200

@pytest.mark.parametrize('width',[390,1440])
async def test_operator_simpan_dan_respons_putus(pg,running,width):
 from playwright.async_api import expect
 uid,kode,mid,intake=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,width,lambda path,method:method=='POST' and path.endswith('/hasil/simpan')) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode)
   root=page.locator('[data-sosoh-ringkas]');field=root.locator('[data-kb-output="medium"] input')
   await field.fill('2100');await root.locator('[data-save-output]').click()
   assert await root.get_by_role('button',name='Konfirmasi pencatatan',exact=True).count()==0
   await expect(root.locator('[data-galat]')).to_contain_text('belum dapat dipastikan')
   assert await field.input_value()=='2100'
   await root.get_by_role('button',name='Baca status terbaru',exact=True).click()
   await expect(field).to_have_value('2100')
   await expect(root.locator('.sr-work-result-balance')).to_contain_text('8%')
   assert sum(path.endswith('/hasil/simpan') for path in writes)==1
   assert not errors,errors
 async with pg() as db:
  assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2300

async def test_neraca_preview_readonly_sumber_dan_izin(pg,running):
 from app.web.sosoh_ringkas import neraca_lembar,Hasil
 uid,kode,mid,intake=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  d=(await c.get('/api/actions/sosoh-ringkas/'+kode)).json()
  async with pg() as db:before=await db.scalar(select(func.count()).select_from(ActivityLog))
  response=await c.post('/api/actions/sosoh-ringkas/'+kode+'/neraca/pratinjau',json={'dasar':d['dasar'],'hasil':[{'jenis':'medium','total':2100}]},headers={'X-CSRF-Token':cap_formulir(c)})
  assert response.status_code==200,response.text
  n=response.json();assert n['susut_kg']==200 and n['susut_persen']==8
  assert next(h for h in n['hasil'] if h['jenis']=='medium')['persen']==84
  async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==before
  # Unknown basis and missing component stay unknown; a legitimate zero stays 0%.
  d['basis_neraca_kg']=None;n=neraca_lembar(d);assert n['susut_persen'] is None
  d['basis_neraca_kg']=2500;n=neraca_lembar(d,[Hasil(jenis='broken',total=0)])
  assert next(h for h in n['hasil'] if h['jenis']=='broken')['persen']==0
  assert next(h for h in n['hasil'] if h['jenis']=='premium')['persen'] is None
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  r=await c.post('/api/actions/sosoh-ringkas/'+kode+'/neraca/pratinjau',json={'dasar':d['dasar']},headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==403

from tests.pg.test_form_selesai_penyosohan import proses
from tests.pg.test_gudang2_operator_pg import gudang2

@pytest.mark.parametrize('width',[390,1440])
async def test_jeda_sisa_dan_selesai_susut_tetap(pg,proses,width):
 from playwright.async_api import expect
 from app.models import User,PolishingProcess,PolishingSiloUsage
 from app.penggilingan.gudang1.services import jeda
 from app.penggilingan.gudang2 import polishing as p
 async with pg() as db:
  await jeda.hentikan(db,user=await db.get(User,proses['user'].id),jenis='penyosohan',kode=proses['kode'],sebab='Listrik padam')
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+proses['kode'])
   root=page.locator('[data-sosoh-ringkas]')
   await expect(root.locator('.sr-status').first).to_contain_text('Dijeda')
   await expect(root.locator('.sr-work-result-balance')).to_contain_text('Susut/selisih sementara')
   await root.locator('[data-kb-output="medium"] input').fill('8000')
   await root.locator('[data-save-output]').click()
   await expect(root.locator('[data-pesan]')).to_contain_text('tercatat')
   await expect(root.locator('.sr-status').first).to_contain_text('Dijeda')
   await root.get_by_role('button',name='Bebaskan Silo B · siklus #1',exact=True).click()
   await root.get_by_label('Sisa fisik di silo (kg)',exact=True).fill('500')
   await root.get_by_role('button',name='Simpan sisa & bebaskan silo',exact=True).click()
   await expect(root.locator('.sr-silo .sr-status').first).to_contain_text('Dilepas')
   await expect(root.locator('.sr-work-result-balance')).to_contain_text('Susut/selisih sementara: 1.300 kg')
   await root.get_by_role('button',name='Periksa & selesaikan penyosohan',exact=True).click()
   await expect(root.locator('[data-sr-finish-balance]')).to_contain_text('Susut/selisih sementara')
   await root.locator('[data-confirm-finish]').check()
   await root.get_by_role('button',name='Konfirmasi selesai penyosohan',exact=True).click()
   await expect(root.get_by_role('heading',name='Penyosohan selesai',exact=True)).to_be_visible()
   await expect(root.locator('.sr-work-result-balance')).to_contain_text('Susut/selisih akhir: 1.300 kg')
   assert not await root.locator('[data-save-output]').count()
   assert not errors,errors
   OUT.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(OUT/f'selesai-{width}.png'),full_page=True)
 async with pg() as db:
  assert (await db.get(PolishingProcess,proses['pid'])).status=='selesai'
  usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==proses['pid']))
  assert float(usage.berat_akhir_kg)==500
  assert await p._total_output(db,proses['pid'],'medium')==8000


async def test_pratinjau_konflik_csrf_dan_susut_negatif(pg,running):
 from app.models import User
 from app.penggilingan.gudang2 import polishing as p
 uid,kode,mid,intake=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  url='/api/actions/sosoh-ringkas/'+kode
  d=(await c.get(url)).json();body={'dasar':d['dasar'],'hasil':[{'jenis':'medium','total':2600}]}
  assert (await c.post(url+'/neraca/pratinjau',json=body)).status_code==403
  r=await c.post(url+'/neraca/pratinjau',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200 and r.json()['susut_kg']==-300
  async with pg() as db:
   assert await p._total_output(db,(await db.scalar(select(__import__('app.models',fromlist=['PolishingProcess']).PolishingProcess).where(__import__('app.models',fromlist=['PolishingProcess']).PolishingProcess.kode_proses==kode))).id,'medium')==2000
   await p.catat_output(db,user=await db.get(User,uid),kode=kode,jenis='medium',berat_kumulatif=2100)
  r=await c.post(url+'/neraca/pratinjau',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==409 and 'berubah' in r.text

@pytest.fixture
async def empat_silo(pg,dunia):
 from app.models import User,Silo,Warehouse
 from tests.pg.test_pk_karung import batch_baru,pindah
 async with pg() as db:
  user,b,it=await batch_baru(db,dunia,n=100,w=5000)
  (await db.get(Warehouse,user.default_warehouse_id)).nama_gudang='Gudang 2 - Uji empat silo'
  db.add_all([Silo(nama_silo='Silo C',warehouse_id=user.default_warehouse_id),Silo(nama_silo='Silo D',warehouse_id=user.default_warehouse_id)])
  await db.commit()
  for silo,qty in [('A',30),('B',30),('C',20),('D',16)]:await pindah(db,user,it,qty,silo)
  proc=(await p.mulai_penyosohan(db,user=user,nama_silos=['A','B'])).proc
  for jenis,kg in [('medium',2000),('broken',120),('bekatul',80)]:await p.catat_output(db,user=user,kode=proc.kode_proses,jenis=jenis,berat_kumulatif=kg)
  return user.id,proc.kode_proses,proc.id

from app.penggilingan.gudang2 import polishing as p

@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('view',[None,'operator:g2'])
async def test_mockup_operator_modal_dua_aktif_dua_bebas(pg,empat_silo,width,view):
 from playwright.async_api import expect
 from app.models import PolishingProcess,PolishingSiloUsage,Silo
 from app.penggilingan.gudang2 import service as g2
 uid,kode,pid=empat_silo
 async with await _klien(pg,peran='superadmin' if view else 'operator',gudang='Gudang 2') as c:
  if view:c.cookies.set('produksi_lihat',view)
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]')
   await expect(root).to_have_attribute('data-layout','operator')
   await expect(root.locator('[data-kb-output="medium"] input')).to_be_visible()
   assert await root.locator('[data-kb-output]').count()==9
   for label in ['Premium','MedSuper','Medium','Ekonomis']:
    await expect(root.get_by_label('Total kumulatif '+label,exact=True)).to_be_visible()
   assert await root.locator('[data-sr-output-samping] [data-kb-output]').count()==4
   assert await root.locator('[data-sr-output-samping] [data-kb-output="sayur"]').count()==0
   field=root.get_by_label('Total kumulatif Medium',exact=True);await field.fill('2100')
   await expect(root.locator('.sr-work-result-balance')).to_contain_text('pratinjau: 2.300 kg')
   toggle=root.locator('.sr-work-source-toggle');await toggle.click()
   await expect(root.locator('#sr-work-silos')).to_be_hidden()
   add=root.get_by_role('button',name='Tambah silo / mix bahan',exact=True)
   await expect(add).to_be_visible();await add.click()
   dialog=root.locator('dialog.sr-silo-dialog');await expect(dialog).to_be_visible()
   await expect(dialog.get_by_label('Silo C · 1.000 kg')).to_be_visible()
   assert await dialog.get_by_role('checkbox').count()==2
   assert not await dialog.get_by_text('Silo A',exact=True).count()
   await dialog.get_by_label('Silo C · 1.000 kg').check()
   await expect(dialog.locator('[data-sr-silo-impact]')).to_contain_text('1.000')
   await dialog.get_by_role('button',name='Tambah silo ke proses',exact=True).click()
   await expect(root.locator('dialog.sr-silo-dialog')).to_have_count(0)
   assert await field.input_value()=='2100'
   await expect(root.locator('#sr-work-silos')).to_be_hidden()
   await toggle.click()
   assert await root.locator('[data-kb-cycle]').count()==3
   release=root.get_by_role('button',name='Bebaskan Silo A · siklus #1',exact=True)
   await release.click();dialog=root.locator('dialog.sr-silo-dialog')
   remaining=dialog.get_by_label('Sisa fisik di silo (kg)',exact=True)
   await expect(remaining).to_have_value('')
   await remaining.fill('400')
   await expect(dialog.locator('[data-sr-silo-impact]')).to_contain_text('1.100')
   await page.keyboard.press('Escape');await expect(root.locator('dialog.sr-silo-dialog')).to_have_count(0)
   await release.click();await expect(remaining).to_have_value('400')
   await dialog.get_by_role('button',name='Simpan sisa & bebaskan silo',exact=True).click()
   await expect(root.locator('dialog.sr-silo-dialog')).to_have_count(0)
   assert await field.input_value()=='2100'
   assert await root.get_by_role('button',name='Bebaskan',exact=False).count()==2
   assert await root.get_by_role('button',name='Konfirmasi pencatatan',exact=True).count()==0
   assert await root.get_by_role('button',name='Periksa & selesaikan penyosohan',exact=True).evaluate("b=>b.classList.contains('btn--utama')")
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   OUT.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(OUT/f'lembar-terbaru-{view or "operator"}-{width}.png'),full_page=True)
   assert not errors,errors
   assert sum(x.endswith('/mix/simpan') for x in writes)==1
   assert sum(x.endswith('/bebaskan/simpan') for x in writes)==1
   assert not any(x.endswith('/hasil/simpan') for x in writes)
 async with pg() as db:
  assert (await db.get(PolishingProcess,pid)).status=='proses'
  usages=list((await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid))).all())
  assert len(usages)==3 and sum(u.berat_akhir_kg is None for u in usages)==2
  silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'))
  assert await g2.hitung_stok_silo(db,silo.id)==400
  assert await p._total_output(db,pid,'medium')==2000

@pytest.mark.parametrize('width',[390,1440])
async def test_simpan_sekali_banyak_jenis_dan_klik_ganda(pg,running,width):
 from playwright.async_api import expect
 from app.services.stok import output_sosoh
 uid,kode,mid,it=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]')
   await root.get_by_label('Total kumulatif Medium',exact=True).fill('2100')
   await root.get_by_label('Total kumulatif MedSuper',exact=True).fill('50')
   await expect(root.locator('.sr-work-result-balance')).to_contain_text('pratinjau: 2.350 kg')
   await root.locator('[data-save-output]').evaluate('(b)=>{b.click();b.click()}')
   await expect(root.locator('[data-pesan]')).to_contain_text('tercatat')
   assert sum(x.endswith('/hasil/simpan') for x in writes)==1
   assert await root.get_by_role('button',name='Konfirmasi pencatatan',exact=True).count()==0
   assert await root.locator('[data-save-output]').is_disabled()
   assert not errors,errors
 async with pg() as db:
  from app.models import PolishingProcess
  pr=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
  assert await output_sosoh(db,pr.id)=={'medium':2100,'medsuper':50,'broken':200}
  assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==4
  assert pr.status=='proses'

@pytest.mark.parametrize('mode',['turun','konflik'])
async def test_gagal_tidak_memotong_isian_dan_tidak_simpan_sebagian(pg,running,mode):
 from playwright.async_api import expect
 from app.models import User,PolishingProcess
 uid,kode,mid,it=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,390) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]')
   field=root.get_by_label('Total kumulatif Medium',exact=True)
   await field.fill('1900' if mode=='turun' else '2100')
   if mode=='turun':
    await root.locator('[data-sr-output-samping]>summary').click()
    await root.get_by_label('Total kumulatif Broken',exact=True).fill('250')
   else:
    async with pg() as db:await p.catat_output(db,user=await db.get(User,uid),kode=kode,jenis='medium',berat_kumulatif=2050)
   await root.locator('[data-save-output]').click()
   await expect(root.locator('[data-galat]')).to_be_visible()
   assert await field.input_value()==('1900' if mode=='turun' else '2100')
   assert not any(x.endswith('/hasil/simpan') for x in writes)
   if mode=='konflik':
    await root.get_by_role('button',name='Baca status terbaru',exact=True).click()
    await expect(root.locator('[data-kb-output="medium"]')).to_contain_text('2.050 kg')
    assert await field.input_value()=='2100'
   assert not errors,errors
 async with pg() as db:
  pr=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
  assert await p._total_output(db,pr.id,'medium')==(2000 if mode=='turun' else 2050)
  assert await p._total_output(db,pr.id,'broken')==200

async def test_modal_putus_setelah_commit_dan_baca_status_tanpa_ulang(pg,empat_silo):
 from playwright.async_api import expect
 uid,kode,pid=empat_silo
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,390,lambda path,method:method=='POST' and path.endswith('/bebaskan/simpan')) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]')
   await root.get_by_role('button',name='Bebaskan Silo A · siklus #1',exact=True).click()
   dialog=root.locator('.sr-silo-dialog');await dialog.get_by_label('Sisa fisik di silo (kg)',exact=True).fill('0')
   await dialog.get_by_role('button',name='Simpan sisa & bebaskan silo',exact=True).evaluate('(b)=>{b.click();b.click()}')
   await expect(dialog.get_by_role('alert')).to_contain_text('belum dapat dipastikan')
   await expect(dialog.get_by_label('Sisa fisik di silo (kg)',exact=True)).to_have_value('0')
   await dialog.get_by_role('button',name='Baca status terbaru',exact=True).click()
   await expect(root.locator('.sr-silo-dialog')).to_have_count(0)
   assert sum(x.endswith('/bebaskan/simpan') for x in writes)==1
   await expect(root.locator('[data-kb-cycle="1"]')).to_contain_text('Dilepas · kosong')
   assert not errors,errors

@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('view',[None,'operator:g2'])
async def test_bentuk_koreksi_hasil_dari_lembar_operator(pg,running,width,view):
 from playwright.async_api import expect
 uid,kode,mid,it=running
 async with await _klien(pg,peran='superadmin' if view else 'operator',gudang='Gudang 2') as c:
  if view:c.cookies.set('produksi_lihat',view)
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]')
   row=root.locator('[data-kb-output="medium"]')
   await expect(row.locator('[data-sr-output-correction]')).to_be_attached()
   await row.locator('[data-sr-output-correction]>summary').click()
   await row.get_by_role('button',name='Koreksi hasil medium',exact=True).click()
   editor=root.locator('[data-koreksi-bahan]');await expect(editor).to_be_visible()
   await expect(root.locator('dialog.sr-correction-dialog')).to_be_visible()
   await expect(editor.get_by_label('Total Medium yang benar (kg)',exact=True)).to_be_visible()
   await editor.get_by_label('Total Medium yang benar (kg)',exact=True).fill('1900')
   await editor.get_by_label('Alasan koreksi / penghapusan (wajib)',exact=True).fill('Salah pencatatan total; diperiksa ulang dengan catatan operator.')
   OUT.mkdir(parents=True,exist_ok=True);await root.locator('dialog.sr-correction-dialog').screenshot(path=str(OUT/f'koreksi-hasil-form-{width}.png'))
   await page.screenshot(path=str(OUT/f'dialog-koreksi-{width}.png'))
   assert await editor.get_by_role('button',name='Periksa dampak',exact=True).count()==0
   await expect(editor.locator('[data-kb-auto-impact]')).to_contain_text('1.900 kg')
   await expect(editor.get_by_role('button',name='Simpan koreksi',exact=True)).to_be_enabled()
   await root.locator('dialog.sr-correction-dialog').screenshot(path=str(OUT/f'koreksi-hasil-dampak-{width}.png'))
   assert not any(x.endswith('/simpan') for x in writes)
   assert not errors,errors
   await page.keyboard.press('Escape')
   await expect(root.locator('dialog.sr-correction-dialog')).not_to_be_visible()
   await row.get_by_role('button',name='Koreksi hasil medium',exact=True).click()
   await expect(editor.get_by_label('Total Medium yang benar (kg)',exact=True)).to_have_value('1900')
 async with pg() as db:
  assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2200

@pytest.mark.parametrize('width',[320,390,1440])
async def test_tema_gelap_geometri_dan_isian_operator(pg,running,width):
 from playwright.async_api import expect
 uid,kode,mid,it=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]')
   await expect(root.locator('[data-kb-output="medium"] input')).to_be_visible()
   await page.evaluate("document.body.classList.remove('terik')")
   for row in await root.locator('[data-kb-output]').all():
    if not await row.is_visible():continue
    a=await row.locator('div').first.bounding_box();b=await row.locator('input').bounding_box()
    assert a['x']+a['width']<=b['x']+1
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   field=root.locator('[data-kb-output="medium"] input');await field.fill('2100')
   await expect(root.locator('[data-kb-output="medium"] .sr-work-percent')).to_contain_text('84%')
   OUT.mkdir(parents=True,exist_ok=True);await root.locator('#hasil').screenshot(path=str(OUT/f'hasil-gelap-{width}.png'))
   assert not errors,errors
   assert not any(x.endswith('/simpan') for x in writes)

@pytest.mark.parametrize('width',[390,1440])
async def test_koreksi_otomatis_satu_simpan_dan_dampak_tanpa_alasan(pg,running,width):
 from playwright.async_api import expect
 from app.models import Peristiwa
 uid,kode,mid,it=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,width) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]');row=root.locator('[data-kb-output="medium"]')
   await expect(row.locator('[data-sr-output-correction]')).to_be_attached()
   await row.locator('[data-sr-output-correction]>summary').click();await row.get_by_role('button',name='Koreksi hasil medium',exact=True).click()
   dialog=root.locator('.sr-correction-dialog');field=dialog.get_by_label('Total Medium yang benar (kg)',exact=True)
   await field.fill('1900')
   await expect(dialog.locator('[data-kb-auto-impact]')).to_contain_text('1.900 kg')
   assert await field.input_value()=='1900'
   await expect(dialog.get_by_role('button',name='Simpan koreksi',exact=True)).to_be_disabled()
   async with pg() as db:assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2200
   await dialog.get_by_label('Alasan koreksi / penghapusan (wajib)',exact=True).fill('Total operator diperiksa ulang')
   save=dialog.get_by_role('button',name='Simpan koreksi',exact=True);await expect(save).to_be_enabled()
   await save.evaluate('(b)=>{b.click();b.click()}')
   await expect(root.locator('.sr-correction-dialog')).to_have_count(0)
   await expect(root.locator('[data-kb-output="medium"]')).to_contain_text('1.900 kg')
   assert sum(x.endswith('/simpan') and '/koreksi-bahan/' in x for x in writes)==1
   assert not errors,errors
 async with pg() as db:
  assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2100
  assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis=='koreksi_bahan_hasil_berjalan'))==1

async def test_preview_koreksi_readonly_tanpa_token_simpan(pg,running):
 from app.models import Peristiwa
 uid,kode,mid,it=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  base='/api/actions/koreksi-bahan/sosoh/'+kode
  d=(await c.get(base)).json()
  body=dict(dasar=d['dasar'],hasil={'medium':1900},alasan='',kunci='uji_preview_koreksi_123456')
  async with pg() as db:
   before=(await db.scalar(select(func.count()).select_from(ActivityLog)),await db.scalar(select(func.count()).select_from(Peristiwa)))
  assert (await c.post(base+'/pratinjau',json=body)).status_code==403
  r=await c.post(base+'/pratinjau',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200,r.text
  assert 'pemeriksaan' not in r.json()
  assert (await c.post(base+'/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(c)})).status_code==409
  async with pg() as db:
   assert (await db.scalar(select(func.count()).select_from(ActivityLog)),await db.scalar(select(func.count()).select_from(Peristiwa)))==before
   assert float(await db.scalar(select(func.sum(PolishingOutputLog.berat_kg))))==2200
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  assert (await c.post(base+'/pratinjau',json=body,headers={'X-CSRF-Token':cap_formulir(c)})).status_code==403

async def test_koreksi_otomatis_respons_putus_tidak_kirim_ulang(pg,running):
 from playwright.async_api import expect
 uid,kode,mid,it=running
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  async with browser_client(c,390,lambda path,method:method=='POST' and '/koreksi-bahan/' in path and path.endswith('/simpan')) as (page,writes,errors):
   await page.goto(BASE+'/proses-aktif/sosoh/'+kode);root=page.locator('[data-sosoh-ringkas]');row=root.locator('[data-kb-output="medium"]')
   await expect(row.locator('[data-sr-output-correction]')).to_be_attached()
   await row.locator('[data-sr-output-correction]>summary').click();await row.get_by_role('button',name='Koreksi hasil medium',exact=True).click()
   dialog=root.locator('.sr-correction-dialog');await dialog.get_by_label('Total Medium yang benar (kg)',exact=True).fill('1900')
   await dialog.get_by_label('Alasan koreksi / penghapusan (wajib)',exact=True).fill('Total yang benar setelah pemeriksaan')
   save=dialog.get_by_role('button',name='Simpan koreksi',exact=True);await expect(save).to_be_enabled();await save.click()
   await expect(dialog.locator('[data-kb-galat]')).to_contain_text('belum pasti')
   await expect(dialog.get_by_label('Total Medium yang benar (kg)',exact=True)).to_have_value('1900')
   await dialog.get_by_role('button',name='Baca data & status terbaru',exact=True).click()
   await expect(root.locator('.sr-correction-dialog')).to_have_count(0)
   await expect(root.locator('[data-kb-output="medium"]')).to_contain_text('1.900 kg')
   assert sum(x.endswith('/simpan') and '/koreksi-bahan/' in x for x in writes)==1
   assert not errors,errors
