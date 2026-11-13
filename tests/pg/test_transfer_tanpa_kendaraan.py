"""Transfer langsung tetap menjaga stok, persetujuan, izin dan idempotensi."""
import asyncio,uuid
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import User,PermintaanPk,InternalTransfer,PengirimanPk,PengirimanPkItem
from app.services import pengiriman_pk as s,transfer
from tests.pg.test_pengiriman_pk_bertahap import siap,buat,tiket,lot_lain
from tests.pg.test_permintaan_empat_langkah import pabrik
pytestmark=pytest.mark.asyncio

async def langsung(pg,w,berat='2000',kunci=None,**extra):
 async with pg() as db:
  return await s.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=w['rid'],berat_kg=berat)],pakai_kendaraan=False,kunci=kunci or uuid.uuid4().hex,**extra)

async def test_langsung_tanpa_identitas_atau_tiket_dan_bisa_campur_perjalanan(pg,siap):
 w=siap;j=await langsung(pg,w)
 async with pg() as db:
  detail=await s.rincian(db,j['id']);assert detail['status']=='selesai' and not detail['pakai_kendaraan']
  assert detail['nomor_polisi'] is None and detail['nama_sopir'] is None
  assert detail['tiket_id'] is None and detail['bobot_timbang_kg'] is None and detail['selisih_kg'] is None
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==2000
  assert await transfer.saldo_pk(db,w['proses_id'])==4000
  assert await s.sisa(db,await db.get(PermintaanPk,w['rid']))==4000
 vehicle=await buat(pg,w,'3000');tid=await tiket(pg,vehicle['id'],3000)
 async with pg() as db:await s.sinkron(db,pid=vehicle['id'],tid=tid)
 await langsung(pg,w,'1000')
 async with pg() as db:
  r=await db.get(PermintaanPk,w['rid']);assert r.status=='selesai' and r.berat_final_kg==6000
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==6000
  assert await transfer.saldo_pk(db,w['proses_id'])==0

async def test_ulang_dan_balapan_tidak_menggandakan_stok(pg,siap):
 w=siap;key=uuid.uuid4().hex
 a,b=await asyncio.gather(langsung(pg,w,'4000',key),langsung(pg,w,'4000',key));assert a['id']==b['id']
 with pytest.raises(s.PengirimanError,match='berbeda'):await buat(pg,w,'4000',key)
 results=await asyncio.gather(langsung(pg,w,'2000'),langsung(pg,w,'2000'),return_exceptions=True)
 assert sum(isinstance(r,s.PengirimanError) for r in results)==1
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==2
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==6000

@pytest.mark.parametrize('extra',[{'nomor_polisi':'K 1 A'},{'nama_sopir':'Kasidi'}])
async def test_tanpa_kendaraan_tidak_menyimpan_identitas_fiktif(pg,siap,extra):
 with pytest.raises(s.PengirimanError,match='tidak memakai'):await langsung(pg,siap,**extra)

async def test_kendaraan_tetap_wajib_identitas_dan_tujuan_tidak_boleh_mencatat(pg,siap):
 async with pg() as db:
  with pytest.raises(s.PengirimanError,match='Isi nomor'):await s.buat(db,user=await db.get(User,siap['op1']),items=[dict(permintaan_id=siap['rid'],berat_kg='100')],kunci=uuid.uuid4().hex)
 async with pg() as db:
  with pytest.raises(PermissionError):await s.buat(db,user=await db.get(User,siap['op2']),items=[dict(permintaan_id=siap['rid'],berat_kg='100')],pakai_kendaraan=False,kunci=uuid.uuid4().hex)

async def test_multilot_kapasitas_gagal_rollback_semua_lot(pg,siap):
 from app.models import Silo
 w=siap;rid=await lot_lain(pg,w)
 async with pg() as db:
  r=await db.get(PermintaanPk,w['rid']);r.silo_id=await db.scalar(select(Silo.id).where(Silo.nama_silo=='Silo A'));r.tujuan='silo';await db.commit()
  await s.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='3000',tujuan='Silo A')])
  silo=await db.get(Silo,r.silo_id);silo.kapasitas_ton=Decimal('1.5');await db.commit()
 args=dict(items=[dict(permintaan_id=w['rid'],berat_kg='1000'),dict(permintaan_id=rid,berat_kg='1000')],pakai_kendaraan=False,kunci=uuid.uuid4().hex)
 async with pg() as db:
  with pytest.raises(s.PengirimanError,match='Kapasitas'):await s.buat(db,user=await db.get(User,w['op1']),**args)
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0
  assert await db.scalar(select(func.count()).select_from(PengirimanPk))==0
  assert await s.sisa(db,await db.get(PermintaanPk,w['rid']))==6000
  silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo A'));silo.kapasitas_ton=3;await db.commit()
  await s.buat(db,user=await db.get(User,w['op1']),**args)
 async with pg() as db:assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==2000

async def test_api_tanpa_kendaraan_tidak_memerlukan_field_armada(pg,siap):
 from fastapi import FastAPI
 from httpx import ASGITransport,AsyncClient
 from app.web.pengiriman_pk import router
 from app.web.deps import pengguna_aksi
 app=FastAPI();app.include_router(router)
 async with pg() as db:u=await db.get(User,siap['op1'])
 app.dependency_overrides[pengguna_aksi]=lambda:u
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as c:
  payload=dict(items=[dict(permintaan_id=siap['rid'],berat_kg='1000')],pakai_kendaraan=False,kunci=uuid.uuid4().hex)
  r=await c.post('/api/transfer-bertahap/pengiriman',json=payload);assert r.status_code==200,r.text
  payload['kunci']=uuid.uuid4().hex;payload['pakai_kendaraan']=True
  r=await c.post('/api/transfer-bertahap/pengiriman',json=payload);assert r.status_code==409,r.text
  payload['pakai_kendaraan']='false'
  r=await c.post('/api/transfer-bertahap/pengiriman',json=payload);assert r.status_code==422,r.text

@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('peran,lihat,is_admin',[
 ('operator',None,False),('admin',None,True),
 ('superadmin',None,True),('admin','operator:g1',False),
 ('superadmin','operator:g1',False),
])
async def test_browser_cara_transfer_dan_simpan_tanpa_kendaraan(pg,siap,width,peran,lihat,is_admin):
 from urllib.parse import urlsplit
 from playwright.async_api import async_playwright,expect
 from tests.pg.test_riwayat_giling import _klien
 base='http://127.0.0.1:59996'
 async with await _klien(pg,peran=peran,gudang='Gudang 1',lihat=lihat) as c,async_playwright() as pw:
  # Lihat sebagai memakai kuki sesi; header Meja lama tidak lagi dibaca.
  if lihat:
   from app.web.lihat_sebagai import NAMA_KUKI
   c.cookies.set(NAMA_KUKI,lihat)
  b=await pw.chromium.launch();page=await b.new_page(viewport=dict(width=width,height=900));errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  async def app(route):
   req=route.request;url=urlsplit(req.url)
   if not req.url.startswith(base+'/'):await route.abort();return
   if url.path=='/api/aliran':await route.fulfill(status=204,body='');return
   response=await c.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data_buffer,headers={k:v for k,v in req.headers.items() if k.lower() in ('content-type','x-csrf-token')})
   await route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding')},body=response.content)
  await page.context.add_cookies([dict(name=x.name,value=x.value,url=base) for x in c.cookies.jar])
  await page.route('**/*',app)
  await page.goto(base+'/transfer-bertahap');await expect(page.locator('#pk-pesan')).to_have_text('Status diperbarui.')
  tutup=page.get_by_role('button',name='Tutup sisa persetujuan',exact=True)
  if is_admin:await expect(tutup).to_be_visible()
  else:
   await expect(tutup).to_have_count(0)
   await expect(page.locator('[data-action]')).to_have_count(0)
   # Pintu API juga memakai peran efektif, termasuk mode operator milik Admin.
   from tests.pg.formulir import cap_formulir
   from app.web import csrf
   response=await c.post(f"/api/transfer-bertahap/permintaan/{siap['rid']}/tutup-sisa",json={'alasan':'Tidak boleh ditutup operator'},headers={csrf.NAMA_HEADER:cap_formulir(c)})
   assert response.status_code==403,response.text
  await page.locator('[name=pilih]').check()
  assert await page.locator('[name=nomor_polisi]').evaluate('e=>e.required')
  await page.locator('#pk-pakai-kendaraan').select_option('tidak')
  await expect(page.locator('#pk-armada')).to_be_hidden()
  assert not await page.locator('[name=nomor_polisi]').evaluate('e=>e.required')
  await page.locator('[name=berat]').fill('6000')
  await page.get_by_role('button',name='Catat transfer selesai · 1 lot',exact=True).click()
  await expect(page.locator('#pk-pesan')).to_contain_text('Stok asal dan tujuan sudah diperbarui.')
  await expect(page.locator('#pk-jalan')).to_contain_text('Transfer tanpa kendaraan #')
  assert await page.locator('#pk-jalan a').count()==0
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  await b.close()
 async with pg() as db:assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==6000
